# Native intraday source attempt: resource-closed — 2026-10-07

## Result and denominator

The single source-only attempt at signed main
`0dee566dd392ff2e969db3aff43d1f1126790c2e` stopped `FAILED_CLOSED` in
`WHOLE_ARCHIVE_INTEGRITY` at 05:00:21 UTC on October 7. BTCUSDT June 14,
2022 exceeded the preregistered **5,000,000-row per-archive guard**. This is a
resource-bound failure, not a detected integrity conflict, unavailable market
price, rejected strategy or negative economic result. No limit was relaxed,
partial scan resumed, alternate day substituted or second source attempt run.
The [signed protocol](STRATEGY-INTRADAY-PROTOCOL-2026-10-07.md) and original
failure remain unchanged.

- Seven of nine fixed archive scans completed: **13,214,561 rows** and
  **177,977,563 ZIP bytes**. The row sum excludes the unreported prefix of the
  failed eighth scan; its exact scanned row count is not retained.
- Eight ZIP/CHECKSUM pairs were downloaded by sixteen fixed GETs. Their ZIPs
  total **244,624,875 bytes**. The ninth ETHUSDT June 14 archive was not reached.
- All four original tapes retain **17,280 slots**, including 17,268 explicit
  no-intent outcomes and **twelve candidates**, without new generation or
  replacement by the annual `PRICE_ONLY` projection.
- The seven completed receipts retain **ten** bracketed
  `RECORDED_PRINT_REFERENCE` witnesses. Two original candidates remain
  **unresolved**, not `NO_REFERENCE`, losses or invalid trades: BTCUSDT June 14
  (failed resource guard) and ETHUSDT June 14 (not reached).

For the ten retained witnesses, the first recorded transaction is 1--736ms
after the separately assumed arrival. Arrival is eligibility +99ms under the
fixed decision +100ms completion/zero transport assumption; this is **not**
measured model latency, local receive time, a quote or our execution delay.
The two no-candidate windows remain in the denominator. Ten of twelve source
witnesses is not an execution-availability estimate, complete sample or
statistically sufficient strategy result.

## Scoped checks, not a completed run

The independent PowerShell partial audit reports `PASSED_PARTIAL_WITNESSES`.
It independently rehashes the retained JSONs, all sixteen downloaded files and
four original tapes; checks SHA256 sidecar contents, completed receipt byte
identity, additive row/byte counts, candidate partition, native TTL/assumed
arrival and bracketing witness arithmetic. It does **not** decompress the ZIPs,
independently repeat CSV order/earliest-print checks, prove the failed member's
CRC or run any economic replay. Raw-ID gaps remain unknown/excluded events,
not automatically missing market data.

The first partial calculator checked only a hypothetical `launch.json` inside
the output directory; the actual signed-source launch receipt is its sibling
`intraday-reference-audit-20261007-a.launch.json`. A separate supplemental audit
binds that real launch receipt, semantic equality of sealed/actual source plans,
the exact first-eight fixed GET pairs, prior source CI and start/failure ordering.
The original partial audit is preserved, not rewritten to broaden its claim.

The first supplemental report also exposed a local PowerShell datetime
conversion defect: the raw launch threshold 04:56:03 UTC was displayed as
01:56:03 UTC, and the start/failure fractional seconds were lost. Preserve
that report and calculator as superseded bookkeeping evidence. A distinct v2
calculator reads raw JSON timestamp strings, compares UTC instants without
local conversion and retains exact source precision. Only its corrected
timeline is used; offline tests bind both versions and detect the three-hour
shift. This correction never reruns or changes the source attempt.

There is **no `result.json`**. The runner's final source/download/native-tape
before/after validation was not reached. Later partial-file hash checks cannot
retroactively certify global run-wide source equality or an accepted complete
source set. `source_prerequisite_resolved=false`; no completed-source or
economic gate is inferred from the ten retained records.

The [lossless evidence index](../development/adaptive_replay/evidence/intraday-reference-2026-10-07/checksums.json)
binds thirty-two original artifacts: failure/start/sealed-plan/launch receipts,
seven completed scan receipts, eight GET-pair receipts, both independent
audits/calculators including the superseded/corrected launch bookkeeping,
launch wrapper/logs and four immutable native decision tapes.
The 244.6MB of raw archives stay in the isolated runtime directory, not Git.
Offline publication tests validate stored bytes, exact roster/clocks,
unresolved outcomes and the refusal to infer qualification; they do not rerun
historical data or download anything in CI.

Publication engineering passes all **382** installed-wheel tests on Python
3.11 (53.91 seconds) and 3.14 (50.85 seconds), including seven new byte/roster/
qualification/timeline checks. Ruff and meta static/local Markdown-link checks
pass. These tests verify engineering and stored evidence only; neither passing
tests nor signed main/green CI can turn a stopped source scan into qualification.

## Selection boundary and next defensible question

This attempt adds partial **recorded transaction-price observability**, not
BBO/depth, executable capacity, an owned fill, exits, fees/funding/PnL,
strategy selection, new forward days or readiness. The provisional
`adaptive_pullback_range_v1` challenger is neither selected nor economically
rejected here. The separate completed annual slow-reference
[no-winner decision](STRATEGY-PRICE-RESULT-2026-10-07.md) remains unchanged.
Neither result is rescued with threshold search or expected future LLM gains.

To reach a defensible final strategy choice, distinct evidence is still needed:

1. A complete accepted intraday source set under a **separately fixed new
   protocol**, not a continuation or weakened pass of this stopped attempt.
2. A predeclared conditional lifecycle/execution contract: causal entry clocks,
   expiry, event ordering, missing-event handling, stop/target/timeout trigger
   and execution delays, partial-capacity assumptions, costs and marked-risk
   breaches. Synthetic conformance is engineering proof, not observed fills.
3. Finite predefined broader coverage and common net-risk comparisons, with
   explicit no-action/unavailable outcomes. A twelve-candidate exposed sample
   cannot be a champion-selection or blind-campaign substitute.
4. Separately qualified executable quotes and eventual venue fill evidence;
   published prints alone cannot close this requirement.

No news/LLM/Macro/Router integration, campaign enrollment, UI, primary recovery,
consumer start, EVEDEX call, paid API request or real order is part of this work.
Trial 15/V4/V5, frozen plans/evaluators, risk ceilings and old evidence remain
unchanged. `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY` and
`LIVE_READY` all stay false; `STRATEGY_POLICY=REJECT_ALL`.
