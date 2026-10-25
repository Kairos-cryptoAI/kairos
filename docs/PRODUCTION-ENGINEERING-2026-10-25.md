# Production engineering checkpoint — 2026-10-25

## Outcome and limits

Three concrete implementation gaps are closed below. This is an engineering
source set, not a complete deployed trader or a deadline-based LIVE approval.
The source identity is in [current-release.json](../config/current-release.json).
All readiness flags remain false and `STRATEGY_POLICY=REJECT_ALL`.

No real order, paid provider call, credential disclosure, legacy database/queue
mutation or frozen research change was made by this work. The old Windows boot
binding was not silently retargeted. Runtime recovery after the newly observed
host restart remains separate from these code results.

## Implemented

1. **Bounded production lifecycle driver.** Execution `03e1766` exposes an
   explicit factory using the existing concrete coordinator. It serializes
   account work, recovers before admission, bounds queue/time/shutdown, and
   defaults to refusing entries. Cancellation/expiry checks run before Risk,
   after Risk and immediately before engine submission. Unknown outcomes latch
   recovery; no automatic replacement or retry is credited. In-flight external
   effects cannot be undone by cancelling a local task. Durable native claims,
   not the process-local queue fence, own restart idempotency. This does not
   bypass an FSM recovery block or the default CLI's LIVE refusal.
2. **Original EVEDEX GET response evidence.** Execution `98ae9dc` retains
   bounded decompressed response-body bytes before JavaScript numeric parsing,
   exact allowlisted method/route/query, status, original local clocks and
   SHA-256. Python verifies the record and parses numbers as Decimal. Parsed
   objects are not reserialized and presented as original bodies. No secret
   headers are captured. This does not prove a shared account snapshot,
   recoverable fills/funding history or an accepted signing domain.
3. **Budget-bound model-call evidence.** LLM `6f2c28a`, with portability fix
   `d91566b`, adds an opt-in synchronous create-only sink. Exact application
   prompts/schema are recorded after durable reservation and before the call;
   a separate completion binds the start only after validated response and
   durable cost commit. Failures retain unknown holds/committed spend, without
   refund or retry. Provider input-token caching is recorded honestly, not
   mislabeled as response reuse. Owner-only local files retain partial and
   conflicting attempts. These are application-boundary records, **not original
   provider HTTP responses**, and do not register a qualified LIVE producer.

Aggregator `863eaa6`, Macro `edca442` and Text `c1de5c7` pin the final LLM
implementation. Deploy `50af49e` aligns current source projections and updates
only the isolated Text/Macro/Router fixture's OpenTelemetry API to 1.45.1.
No historical campaign dependency set was rewritten.

## Verification

| Scope | Actual local result |
| --- | --- |
| Execution non-integration suite | 1085 passed, 1 skipped, 54 deselected; 8 subtests |
| Existing coordinator and new driver on isolated native PostgreSQL | 2 passed; synthetic venue/account/signers |
| Pinned SDK sidecar | 42 tests passed |
| LLM full suite | 292 passed, 6 skipped |
| Aggregator / Macro / Text on fresh noneditable dependency installs | 97 / 92 / 106 passed; Macro 1 skip, Text 1 deselection |
| Deploy validators/tests after final fixture dependency refresh | 1160 tests passed, 8 skipped |

Execution and LLM passed lint, formatting, typing and Bandit. LLM typing was
checked against Windows and Linux after a real Linux CI failure exposed
unguarded Windows-only ctypes calls; that failed run is retained.

Affected exact-commit CI:
[Execution](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40204781007),
[LLM](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/40205338576),
[Aggregator](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/40205499275),
[Macro](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/40205499234),
[Text](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/40205498506).
Deploy's final source-set CI is recorded separately on its exact HEAD; a local
pass does not stand in for a pending remote job.

Local JUnit evidence is retained under
`D:/Kairos/runtime/production-finish-20261025/d5fc09160294416696baa1840156fb6b/`.
An initial one-CPU native fixture run had one deadline failure and one pass.
Both later tests passed with a two-CPU fixture; this does not establish CPU as
the root cause or qualify production latency. The failed run was not removed.
The exact owned disposable PostgreSQL container was then stopped cleanly; its
volume and partial evidence remain. No other container was stopped by this work.

## New host incident, not a current uptime pass

The earlier [host acceptance](CURRENT-HOST-RECOVERY-2026-10-25.md) remains a
historical bounded result. A later Windows restart was observed at approximately
14:13 UTC / 17:13 Moscow. The exact owned PostgreSQL, Redis and serve containers
for `3652db45719547b18fad1d6ff10ea002` all exited with code 255 at 14:15:06 UTC;
their inspected OOM flags were false. The final status at 14:12:03 UTC is stale,
not current health. This correlation is not a completed root-cause analysis.

The old immutable profile binds Deploy `92c4847`. The current source check
requires an exact clean signed release; it does not permit silently treating
the new metadata-only descendant as the old receipt. New-source recovery and
boot acceptance must use the supported owned path, not edited receipts, removed
locks or a weakened source gate. No actual post-restart recovery is credited
by this document.

## Still required for real-money operation

- A real native upstream capture/composition using Text, Macro, Router and
  review, with qualified original-source provenance. The new model-call hook
  alone does not supply it. Research SIM envelopes are not LIVE envelopes.
- Authoritative EVEDEX account/economics/terminal sources and confirmed PROD
  signing/custody semantics. No support reply was present in the existing
  inquiry thread at this checkpoint. Existing verifiers continue to refuse
  incomplete evidence; possessing an API key is not qualification.
- Deploy and accept the complete current service, current-owner recovery,
  boot and alert path, then confirm explicit capital/loss limits and separate
  manual arming. The non-trading data worker is not that service.

No profitability, professional-trader equivalence or permission to trade is
inferred from fixture success or the requested release date.
