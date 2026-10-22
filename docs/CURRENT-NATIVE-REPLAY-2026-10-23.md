# CURRENT native replay: verified engineering, incomplete real E2E

This continues the October 22 verification across midnight in Europe/Moscow.
Original artifact directories and timestamps are retained. **A complete real
news/model/Risk/SIM entry and closure are not verified.**

## Implemented path

The adapter now records one new original globally chained V2 native tape,
retains actual decision requests separately, imports full real bar provenance
and native frames before sealing, and only then runs existing native SIM.
Actual observation and later replay clocks are distinct. Old segment tapes
are not stitched, re-rooted, rewritten or reopened.

Request bytes, durability receipts, original frame watermarks, source/model
identities and tape seals are checked. A later same-ms frame cannot conceal an
earlier omitted frame. Entry outside the original session is refused; a candle
already closed at entry cannot trigger its exit. Insufficient future evidence
leaves an incomplete lifecycle, never a fabricated closure.

The original limits remain: one connection, no retry/reconnect, at most
900 seconds / 60,000 frames / 128 MiB raw payload; exact TEXT/frame byte/count
denominators; five-second source freshness; two-second original quote expiry.

## Real source / native persistence preflight: passed

`D:\Kairos\runtime\current-system-20261022\run-35c63dae4dbb4868b970bbae04387aa6`

- 16,200 real closed Binance minute bars: 3,240 per fixed instrument.
- 7,855 original V2 frames and TEXT deliveries; both raw-byte denominators
  4,900,034 bytes; all five instruments present; no source failure.
- Full tape imported, sealed and verified before creating the native session.
- Tape SHA-256: `b80218c16579468de416d33423d3baefb98726ed94254cbebec070b915fae6ef`.
- `native-tape-verification.json`: `PASS_RECORDED_NATIVE_SOURCE_TAPE_ONLY`.
- Zero provider calls and trade requests. Owned SIM stopped/retained; only its
  credential-free tunnel removed. This is not model, entry or closure credit.

## One real model run: failed closed

`D:\Kairos\runtime\current-system-20261022\run-5dc25a1f9e8449beb5b0a68e22d8806e`

Actual inputs included the complete bar history, timely Cointelegraph RSS,
observed Quant data and 15 official Federal Reserve publication summaries.
BLS CPI returned HTTP 403; numeric macro releases are unavailable, not zero.
Summaries are not the full linked statements.

Six actual uncached replies: one Macro `gpt-6.1-sol`, five Catalyst creation
assessments `gpt-6-luna`. Registered-price ledger cost: **96,483 microusd
($0.096483)**, not a reconciled provider invoice.

The timely Dune data-feed story was rejected by native Text Scouts relevance:
`fetched=1, timely=1, kept=0`. No text-model call occurred. Three creation
assessments returned SHORT, two NONE, but no Catalyst plan materialized. There
was no native review, Risk admission, SIM order, fill or closure.

After model processing, twenty synchronous arm resolutions repeatedly
revalidated all 16,200 bars without yielding to the source reader for about
124 seconds. Capture correctly failed `SOURCE_GAP`: 11,271 admitted frames,
11,272 retained TEXT deliveries. No seal/admission was manufactured from it.
The outer `bootstrap-failure.json` overrides the inner traversal's COMPLETED
marker. Its owned SIM is stopped/retained; its tunnel was removed.

Shared budget afterwards: committed 241,087 microusd, historical 1,984,
unknown/reserved holds 159,659, unchanged cap 12,000,000. Remaining after holds:
**11,597,270 microusd ($11.597270)**. Unknown holds were not reset/refunded.

## Corrections and actual load check

Heavy pure Catalyst folds now run sequentially in **one spawn process**, keeping
original inputs/clocks and all validation. Provider/database coroutines stay
on their owner loop. Small hashes/file writes are awaited separately; owned
work is drained on cancellation. No parallel strategy arbitration is added.

A thread-only check also failed: shared-interpreter contention caused native
`DELIVERY_QUEUE_OVERFLOW`. Its artifacts remain in
`retained-real-load-76f0c211ee514353a3da8cbaf749b135`. Queue/freshness limits
were not increased; failed writer/receiver races now retrieve terminal errors.

The corrected process-isolated check passed:

`C:\Users\loval\Documents\ChatGPT\Kairos\current-system-public-capture-20261022\retained-real-load-b65d3a188e604bd8a0c91e66676eb5f8\verification.json`

- Fifteen original real bar pages hash-checked: 16,200 retained real bars.
- Twenty native fold resolutions executed sequentially.
- Concurrent real stream: 3,645 TEXT messages/frames, 2,272,559 payload bytes,
  all five symbols, no failure; maximum heartbeat interval 125 ms.
- Zero paid calls, new databases or orders. Missing context stayed UNKNOWN.
- Result `PASS_SOURCE_SCHEDULING_ONLY`: no model/trade verification credit.

Full verification now applies the unchanged native normalizer, freshness,
deduplication and relevance filter before paid work. An actual new RSS check
retained one timely item but selected zero at threshold 3.0, correctly refusing
before paid stages. Its create-only receipt is:

`C:\Users\loval\Documents\ChatGPT\Kairos\current-news-model-preflight-20261023-3865bf16db\news-model-eligibility.json`

## Remaining acceptance and safety

Full acceptance still requires actual selected news/text-model output, current
Macro, a naturally valid Catalyst plan, native Router/review, Risk admission and
native entry together. Closure is separate. Persistence/scheduling checks do
not replace this evidence. Both reviews and entry must still meet the original
two-second quote deadline; real slow responses cause refusal.

No second paid run followed the failure. No EVEDEX/PAPER/LIVE service, primary,
legacy or R7 database/queue was changed. Strategy, frozen research evidence and
evaluators remain untouched. No alpha, profitability, blind or LIVE credit.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.

Signed main implementation: `7aa0c33`, `a672177`, `95c7dd6`, `13bd24d`, `b0a5c0c`.
The source-only check/model attempt used attested `a672177`; the successful load
receipt records exact corrected file hashes. Final local suite: **103 passed,
1 explicitly opt-in durable test skipped**. Ruff/format and diff checks passed.

## Later separately approved CURRENT profile

The original runs and their two-post-quote-review semantics above are retained
unchanged. A subsequent owner-approved version reviews the immutable plan
before obtaining a new executable quote, while keeping the two-second entry
freshness and independent Risk/SIM gates. See
[the separate version and actual attempt](CURRENT-PLAN-REVIEW-2026-10-23.md).
Its green engineering/CI checks and real free-news refusal are not credited as
a completed real E2E test or a repair/rewrite of the old receipts.
