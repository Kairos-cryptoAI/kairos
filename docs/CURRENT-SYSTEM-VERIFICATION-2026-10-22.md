# CURRENT Catalyst system verification — 22 October 2026

Later implementation and real-source results are recorded in
[CURRENT native replay, 23 October](CURRENT-NATIVE-REPLAY-2026-10-23.md).
The initial finite-tape diagnosis below is historical, not the current driver.

**Result: PARTIAL_REQUIRED_STAGES_NOT_EXERCISED, not a full real E2E PASS.**

This report concerns the CURRENT Catalyst/Text/Macro/Router/review/Risk/native
SIM integration, not the old twelve-candidate reconstruction. Offline tests
are supporting engineering checks, not substitutes for real source/model fills.
No profitability, historical point-in-time result or blind-campaign credit is
claimed. All readiness flags remain false and strategy policy is REJECT_ALL.

## Real bounded run

Receipt root:
`D:\Kairos\runtime\current-system-20261022\run-74ac4c08f1294dcea342f62010c6a660`.

The declared cut was **21:05 MSK / 18:05 UTC**. `current-chain-result.json`
records traversal completion; the separate `verification-acceptance.json`
binds the input hashes and explicitly refuses full real-path acceptance.

| Evidence | Observed result |
| --- | --- |
| Public bars | 3,240 closed 1m bars per symbol, 16,200 total, five-symbol 54h capture |
| Quant | Actual funding/OI/13-point OI history, with a separately scoped connected force-order window |
| Original native WS | 456 delivered and admitted messages, all five symbols, two immutable segments |
| SIM segment | Latest complete original segment, 200 original frames; no tape-ID/hash rewriting |
| Official macro context | 15 actual Federal Reserve monetary-publication summaries; original dates retained |
| Numeric macro coverage | BLS CPI endpoint returned HTTP 403; no CPI/rates/on-chain values fabricated |
| News admission | Captured CoinDesk RSS had zero items within the existing 30-minute gate |
| Text model | Not called; actual TextScouts correctly had no timely items |
| Macro model | One actual OpenAI `gpt-6.1-sol` response, not defensive fallback |
| Macro output | BEAR, stable reserve 100%; not evidence that the forecast is profitable or correct |
| Catalyst | Five actual slots, four arm dispositions each; QUIET / NO_NEW_EVENT, no manufactured plans |
| Native review/Risk/orders | Not exercised by this real cut; no SIM admissions or commands |

Actual provider evidence is in `provider-01.request.json`,
`provider-results.jsonl` and `budget.jsonl`. One shared-campaign reservation
committed **89,819 microUSD ($0.089819)** under the existing registered pricing
table, not a verified provider invoice. The cumulative $12 authority was not
reset: historical 1,984; committed 144,604; unchanged prior unknown holds
159,659 microUSD. Remaining capacity after holds: **$11.693753**.

No OpenAI calls were made in the earlier failed source-capture attempts.
There were no DeepSeek/X paid calls, EVEDEX requests, real orders or changes to
old runtime databases/queues. Only a newly owned SIM database was created.

## Durable real-source evidence, not simulated fills

The owned container `kairos-current-sim-c8a783546ec5` was stopped and retained
after the run. Its exact container ID, owner label and immutable image were
checked before restarting **only that container** for a read-only transaction.
The post-restart check found one sealed tape, 200 book frames, 10 observed
closed bars and one session. Risk decisions, admissions, commands and trade
results were all **zero**. It was stopped again; no old runtime was restarted.
See `post-restart-readonly-audit.json`.

A subsequent **read-only retrospective adjudication** applied the new guard to
the original retained cut, not to an invented earlier clock. The original
Quant prefix was verified at 482,068 bytes / 906 rows / SHA-256
`3d155eb7bfa1fa67e187b61f75f7d74856d20c78e823d6e2fdd428ba71da99bd`.
It contains two actual closed bars per symbol, matching the audited total of
10; at least 3,238 of the 3,240 history bars per symbol are absent from the
initial seal. The selected original book frames are **357,495–357,500 ms old**
at the declared cut, against the unchanged 5,000 ms gate. Their original source
latencies are 218–295 ms; the problem is their age at decision, not an invented
transport-latency failure. This adjudication made zero paid calls, changed no
old receipt and restarted no resource. See
`execution-compatibility-adjudication.json` and the separately appended
`verification-acceptance-strict-cache.json`.

The original public-source audit independently returned
`PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY` for all 456 source messages. That proves
retained source consistency, not complete market coverage, independent source
authenticity, native execution admission or trading qualification.

## Remaining source checks

The other existing RSS source, Cointelegraph, was checked separately: 30 retained
RSS items, zero timely admitted items at that observation. Dates were not renewed.
The CoinDesk snapshot's newest publication was 15:40:25 UTC, earlier than its
18:00 local capture by more than the allowed window.

The existing primary GDELT endpoint was also checked with its configured query,
three-record bound and no retry/redirect inside either attempt. The first
diagnostic timed out connecting; the second returned **HTTP 429**, not a proven
empty news feed. No model call or source admission followed either diagnostic.
Receipts are under
`C:\Users\loval\Documents\ChatGPT\Kairos\current-news-probe-20261022-a`.
Index/aggregator timestamps alone are not treated as independent proof of the
publisher's original publication time. The API's official query documentation is
[GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

## Implemented fixes

- Actual Catalyst plans use the Catalyst fold, not the older V3 fold.
- Real typed/dataclass stage results and candidate identities are retained
  without calling nonexistent model methods or serializing opaque clients.
- Strict contract validation preserves Python datetime/enum types. Current
  hypothesis IDs and refreshed selected-plan market receipts are kept exact.
- Native capture starts after verified TLS/WS setup. Ordered bounded recording
  does not block delivery while segment validation is running; original bodies,
  arrival/persistence clocks and freshness gates remain intact.
- New public artifacts use the faster C: volume. Failed D: and C: attempts are
  retained, not deleted or relabeled. Queue overflow remains fail-closed.
- Original segment roots are selected explicitly for SIM, never flattened into
  a different tape ID. Market event matching respects Binance's camel-case
  names; a Quant window closes only after its actual boundary record is retained
  and processed, including a force-order event on that boundary.
- Current Core/Persistence service pins, locks and current deployment projections
  are coherent. Historical/recovery/research locks and frozen evidence were not
  rewritten. V2 observed-SIM intents remain categorically barred from PAPER/LIVE.
- Real-path acceptance is separate from `COMPLETED`. A partial traversal returns
  exit code 2. `--require-fresh-news` refuses an empty/stale news snapshot before
  paid stages; there is no automatic paid retry/polling loop.
- A necessary-condition pre-paid check now refuses the diagnosed frozen initial
  tape: it records actual per-symbol frame ages at the earliest possible cut,
  original IDs and missing-provenance count lower bounds. It cannot be bypassed
  to pay for another structurally unexecutable cut. This closes a wasteful
  admission path, not the forward-execution integration gap itself.
- SIM entry evaluation now waits for the actual assumed command-arrival time
  rather than passing its earlier admission timestamp once and leaving `WAIT`
  unprocessed. Original submission/expiry and source clocks are not changed.

## What is still not established

1. A real timely-news model response, a naturally materialized Catalyst plan and
   its real native review have not been observed together in this run. A quiet
   cut or a veto must not be forced into a trade merely to increase test coverage.
2. Real native Risk admission, entry fills, protection and trade closure have not
   been established. The positive PostgreSQL/controller fixture is explicitly
   synthetic input/model engineering evidence and supplies **no real-path credit**.
3. The current prospective driver still starts from a finite, sealed initial
   tape. It is not a continuous forward execution feed: initial frames can be
   stale after model processing, and future bars cannot be appended to the same
   immutable seal. Before a positive forward-SIM claim, the driver must reconcile
   actual fresh frame/provenance capture and immutable session sealing. Original
   two-second quote expiry and actual model latency cannot be renewed/backdated.
   This report does not call that engineering gap closed.
   The current native controller is explicitly an offline sealed-tape replay
   controller, not a live growing-tape execution service. Its source recorder
   also creates distinct immutable segment roots; merging or rehashing those
   roots into a pretend continuous tape is not an admissible fix. A preview
   review completing after the original two-second quote expiry must refuse;
   a new Risk book cannot heal that expiry.
4. Numeric macro-release coverage remains partial. Federal Reserve summaries do
   not stand in for missing CPI, rates, consensus or full linked statements.

The next paid test should not repeat the same empty source cut. It needs admitted
fresh input and real conditional branch coverage, after the forward/sealed-tape
integration issue above is resolved. No new strategy, profile relaxation,
artificial event, retrospective timestamp or fixture result may substitute.

## Verification boundaries

Core contract regressions, Risk SIM-only refusal tests and current-source
composition/full-path gates were run separately. The new whole-run offline
fixture uses actual current object types and components, with only source/model
transport/persistence boundaries fixed. It is not counted in the real result.

GPG-signed main implementation: `6763bee16c49fa47547d8fed1b015cace265844f`.
Current dependency identity: `983e7fbcc86c37208b5db98c482eaff220e96ab6`.
At that identity, all 14 local main checkouts were clean and matched origin/main;
the corresponding Validate, current-chain Windows/Linux and native-campaign
checks passed. Deploy `6d9fe07812c8cb4a274764d685e97c7fe199a419` also passed CI,
current-release, full-path SIM and installed Text/Macro/Router/review/Risk gates.
These are engineering/source gates, not a statement of complete real E2E success.

After adding strict partial-run acceptance, pre-paid tape compatibility checks
and actual command-arrival waiting, the local current-chain regression suite
passed **70 tests, with one explicitly opt-in durable test skipped**. Ruff and
`git diff --check` passed. These checks made no external/provider requests and
do not supply the missing real branch coverage described above.
