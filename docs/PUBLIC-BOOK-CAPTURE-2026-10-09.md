# Public native book capture: isolated research source producer

## Scope

This is an additive producer for the October 9 causal-source task. It does not
upgrade the old V1 recorder, recover past BBO from candles/prints, resume a frozen
experiment, accept a complete source set, operate the primary DB or grant any
trading/readiness authority. Historical attempts and their missingness survive.

`development/adaptive_replay/adaptive_replay/public_book_capture.py` subscribes
to the five fixed Binance UM `depth10@100ms` streams using one public connection.
The [official partial-book documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public)
specifies `/public/stream` and the migrated `st`/`ps` fields. The new producer
selects that exact migrated profile; unexpected schemas are refused, not adopted.

## Capture contract

- Default CLI is a no-op. `--capture` requires a new direct runtime child named
  `public-book-capture-YYYYMMDD-suffix`. No overwrite/resume or automatic retry.
- One OS-owned lock excludes a second capture across output directories. Kernel
  ownership ends at process exit; old partial outputs/receipts are never removed.
- One verified TLS hostname/certificate connection, no redirects, environment
  proxy, authentication, private account or paid API. No reconnect loop.
- At most 120 seconds, 6,000 delivered text messages and 16 MiB original payloads;
  one message is bounded to 32 KiB. These are cooperative application bounds,
  not a claim that every wire packet or exchange market tick was observed.
- Exact delivered UTF-8 text and local delivery UTC/monotonic clocks are written,
  flushed and fsynced **before** native normalization. Original persistence time
  is sampled only after that fsync. A rejected parse remains in raw evidence.
- Native frames rotate into unchanged create-only V2 bundles every 256 frames.
  Local bundle roots are not new exchange epochs: the manifest binds global raw
  ordinals, received-record heads, ordered segment commitments and one physical
  epoch. Per-symbol update/event clocks and local persistence never reset there.
- Missing symbols, event age or observed gaps over five seconds, clock regression,
  schema conflict, resource exhaustion and disconnect fail closed. The complete
  observed/admitted denominator and a terminal receipt are retained; a failed
  segment retention cannot turn the attempt into a success.

## Independent read-only reconciliation

`audit_public_capture(output, expected_receipt_sha256=...)` requires a separately
held terminal-byte commitment. It checks plan/source identity, transport claims,
all original messages, every bundle/segment receipt, local/global hash chains,
clock/order/freshness constraints, all five symbol counts and boundary gaps.
It neither rewrites a failed receipt nor substitutes a sampled subsequence.

The auditor reports only `PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY`. TLS observation
is not an exchange signature; local UTC is not independent clock attestation;
top-ten snapshots are not continuous full-depth/tick completeness. The capture
contains no accepted bars/news/macro/model source set or execution qualification.

## Remaining task

One real bounded capture and its read-only byte audit are now recorded in the
[dated source observation receipt](CAUSAL-SOURCE-OBSERVATION-2026-10-09.md).
It is a thirty-second sampled native source, not a complete historical corpus.
The failed HDD attempts remain failed and retained. The active objective still
includes continuous portfolio hypothesis SIM with original intraminute entry
and trailing protection, real causal news/macro/history inputs and a fixed
full-system matched comparison. Recorder fixtures and the native source audit
do not close those requirements or select a strategy.

The existing locked `aiohttp` version is now an explicit development-package
dependency. No library version, native service pin, production projection or
release readiness flag changes. All readiness remains false / `REJECT_ALL`.
