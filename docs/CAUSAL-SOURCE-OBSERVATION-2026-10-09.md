# Causal source observation — October 9, 2026

## Scope and outcome

This is an actual bounded public-source observation, separate from the frozen
Trial 15 and quarter-hour experiments. It does not admit a complete source set,
backdate source availability, qualify execution or select an economic winner.
No paid model, exchange account, primary database or trading process was used.
All four release readiness flags remain false; policy remains `REJECT_ALL`.

The new native producer has one successful observed-source consistency audit.
The official context producer retained one partial attempt: Fed succeeded,
BLS returned HTTP 403. Neither result closes the full causal historical corpus.

## Native source attempts, without overwriting failures

| Attempt | Location | Observed / admitted | Terminal result |
| --- | --- | --- | --- |
| First HDD attempt | `D:\Kairos\runtime\public-book-capture-20261009-a` | 1 / 0 | FAILED; exchange event ahead of local receive clock |
| Second HDD attempt | `D:\Kairos\runtime\public-book-capture-20261009-b` | 209 / 208 | FAILED; final event age 5,108 ms exceeds unchanged 5,000 ms limit |
| Separate SSD attempt | `C:\Kairos\runtime\public-book-capture-20261009-a` | 1,280 / 1,280 | CAPTURED; five retained native segments |

The first two attempts and original receipts are preserved. No failed message
was dropped to promote an attempt; no resume, reconnect, retry loop, timestamp
rewrite or relaxed freshness threshold was used. The SSD output is a new runtime
directory, not a move of old data, repositories, primary storage or evidence.

Read-only disk inventory maps C to WD_BLACK SN7100 NVMe and D to ST4000DM004 SATA.
The second HDD attempt's increasing receive-to-exchange delay and synchronous
per-message flush/fsync justified a separate bounded SSD observation. This
comparison does not independently establish whether storage, scheduling,
network or source delivery caused every part of the prior delay.

Descriptive SSD distributions give median receive-to-exchange event age of
265–266 ms by symbol, with maxima 3,209–3,256 ms. Receive-to-persistence delay is
0 ms at the median, 1 ms at p95 and 1–2 ms at maximum. The second HDD attempt's
corresponding persistence medians were 26–37 ms and maxima 247–271 ms.
Independent read-only concatenation found no per-symbol update/event/receive
regression across all five segment boundaries. Source-event tail delay remains
visible; changing the disk did not make source/network timing disappear.

The SSD attempt requested 30 seconds and retained a 33,016 ms terminal monotonic
span, including bounded finalization. Its five admitted symbol counts are
BNB 228, BTC 261, ETH 270, SOL 259 and XRP 262. Original UTF-8 payloads total
796,061 bytes. The raw archive is 1,408,012 bytes; it also retains local clocks
and hash-chain fields. Maximum observed inter-delivery gaps range from 3,048 to
3,117 ms; terminal symbol gaps range from 3,580 to 3,651 ms. All are below the
existing five-second limit. These are observed delivery gaps, not proof that
every market tick was received.

After separately recording the terminal receipt SHA, the preserved installed
wheel's `audit_public_capture` returned
`PASS_OBSERVED_SOURCE_CONSISTENCY_ONLY` for all 1,280 originals and five segments.
The `load_public_book_tape` immutable-byte loader accepted the same committed
capture without mutating it. It verifies a bounded raw-byte snapshot against the
terminal commitment before parsing; a second folder audit is not a substitute
for authenticating the bytes actually consumed.

| Artifact | SHA-256 |
| --- | --- |
| SSD terminal `receipt.json` | `30e524480a58c3acf993e1b94a0b8d05a643dd2dc5ed81b1b8142d9a2ad495fd` |
| SSD `received.raw.jsonl` | `66a3d8c94694d395653ecaefd71161653bd5d5241ee83e29c91e2616ef7602ff` |
| Second HDD failed terminal receipt | `e6feafa5afc6cd1c4113b5faaafc95378cb288ecca3a3fa54488f592f2a2c491` |

This is sampled Binance UM top-ten observation, not a continuous full-depth
archive, exchange-signed evidence, independent clock attestation or EVEDEX
execution qualification. The receipt explicitly retains
`market_tick_completeness=UNKNOWN_NOT_CLAIMED`, `source_set_admitted=false` and
`risk_authority=NONE`.

## Local clock diagnostic

A bounded elevated helper corrected local UTC by +0.7028521 seconds relative to
the already configured Windows NTP peer. Four pre-correction samples passed the
helper's agreement/bound checks. Three post-correction offsets were 9.2908,
9.0866 and 8.8133 ms; a later read-only three-sample check was below 1 ms.
The actual child transcript contains its completion marker; parent launcher
exit alone was not used as success evidence. The helper used process-scoped
`RemoteSigned` and changed neither machine execution policy nor the NTP peer.

Transcript: `D:\Kairos\runtime\public-book-gates-20261009-a\clock-correction-diagnostic-c.log`.
The correction is not independent trusted-UTC attestation and does not repair
or re-admit the earlier failed capture. W32Time remains running with its existing
manual startup mode.

## Official context attempt

The create-only archive at
`D:\Kairos\runtime\official-context-20261009-a` contains exactly two bounded
GET attempts, verified default TLS, no authentication, environment proxy,
redirect or retry:

| Official source | HTTP | Retained bytes | Parsed versions |
| --- | --- | --- | --- |
| [BLS CPI release](https://www.bls.gov/news.release/cpi.htm) | 403 | 1,319 | 0; UNAVAILABLE |
| [Federal Reserve monetary RSS](https://www.federalreserve.gov/feeds/press_monetary.xml) | 200 | 9,649 | 15 |

The 403 body and missing macro result remain explicit. No response spoofing or
access-control bypass was attempted. Read-only context auditing returned valid
byte/schema/reparse consistency for the retained attempt, not full source
admission. Coverage remains UNKNOWN; historical availability, historical receive
clock and provenance authenticity are not proven. Fifteen publications fetched
now cannot be presented as text known to Kairos before a 2021 event.

| Artifact | SHA-256 |
| --- | --- |
| Context terminal receipt | `bf185b8eb75b19b6cff9e31685c93a91722f12190d9dcae3e41f958d39ce6897` |
| Context archive | `f70ae79bf96482ec636e9f6ab18e8e32ef4cf510b1e7cc24b30fe5b9bc16ffbd` |
| Fixed parser source | `d0def39a5f033b4844f11fdff5fc1c9313b9de502977ec8353d7d38c625b5e2c` |

The parser preserves original response bytes, distinguishes local availability
from published time and does not truncate extra RSS items silently. Stable Fed
document identity binds GUID and URL; version provenance also binds raw feed
bytes. CPI period end must precede publication; minute-precision publication is
represented as an interval, not an invented exact second. The extraction-policy
fingerprint binds the actual parser source.

## Preserved execution snapshot and verification boundary

These captures were run from a non-editable installed development wheel,
not a source tree concurrently changing during the observation:

`D:\Kairos\runtime\public-book-gates-20261009-b\dist\kairos_adaptive_development_replay-0.1.0-py3-none-any.whl`

SHA-256: `20c86e4dbf20f90a622dfb9e6be73b1d37e0de2d660fcde297878fe0d75ad5ca`.
Do not overwrite this wheel when building later portfolio SIM changes; the
capture and native bundle implementation identities bind this snapshot.

The Python 3.11 capture/context/mapping fixture gate passed 67 tests with two
platform symlink-privilege skips. Account/journal/codec/mapping fixtures passed
67 tests. These are synthetic engineering checks, separate from the actual
read-only capture audits and from final full-suite/CI evidence.

The later immutable component wheel under
`D:\Kairos\runtime\public-components-gates-20261009-c\dist` has SHA-256
`7fc20561f04c4b9f082fd4eaef568ef5845b8150d1f04b76d0d1dd76e58c035f`.
With `--import-mode=importlib -W error`, each complete non-portfolio component
suite passed 1,468 tests with four platform skips on Python 3.11 and Python 3.14.
JUnit files are retained as `public-components-py311.junit.xml` and
`public-components-py314.junit.xml` in that gate directory. This suite explicitly
excluded `test_continuous_sim.py`; it is not the final portfolio SIM gate.
The preceding Python 3.14 failures exposed unclosed HTTP error responses and
fixture SQLite handles; deterministic closure was fixed, not warning-filtered.
New account checks reject non-boolean safety flags and reserve known immediate
spread/fee losses against current-equity limits. These engineering corrections
do not alter production Risk Manager, frozen strategies or old source receipts.

The final isolated portfolio snapshot under
`D:\Kairos\runtime\continuous-sim-gates-20261009-d\dist` has wheel SHA-256
`1c9e4dbd1e4642700a366f23dccccce2d8682d3cd13b4536bf5c24ac4c9e6143`.
Its complete installed-wheel suite, including the 22 portfolio tests, passed
1,490 tests with four explicit platform skips on each Windows Python 3.11 and
Python 3.14. Both used `--import-mode=importlib -W error`; actual terminal times
were 289.82 and 230.07 seconds. The retained `full-py311.junit.xml` and
`full-py314.junit.xml` are local fixture evidence, not hosted CI or an observed
continuous historical trading result. No warning filters or source/exit/risk
threshold relaxation was used to obtain these passes.

The development lock adds an explicit already locked aiohttp dependency and
pins the execution simulation kernel at immutable main SHA
`ef91f99c3e1cec6a1e5f825f031c649a79656783`. It does not change a native service
projection, production manifest pin, frozen research lock or readiness flag.

## Work still open

- Accepted continuous bars/book/news/macro coverage with causal availability,
  original bytes and explicit missingness, including the selected historical
  scenarios. A sampled book capture and partial current Fed feed do not supply
  the historical corpus.
- Real-source integration of the durable multi-hypothesis, five-symbol SIM per
  isolated matched arm. Fixture mechanics now cover the original risk/protection
  lifecycle, partial fills, shared liquidity, restarts, exposure-time funding
  and complete candidate/quiet/unavailable denominators; this does not supply
  accepted continuous inputs or a completed historical run.
- One fixed full-system matched economic comparison and defensible final
  strategy identity. No model was called and no LLM profit result exists here.

No synthetic PASS, local source audit or unmeasured LLM-filter assumption closes
these three points. No new blind campaign starts from this receipt; its own
sealed identity and 365-day/500-natural-close gates remain separate.

The bounded portfolio runner now has 22 passing full-path synthetic tests,
including sequential hypotheses on one shared account, isolated arm liquidity,
partial fills, all original exits, target-to-stop escalation, first-fill timeout,
closed-candle trailing, late funding after natural flat, restart/dedup and
unavailable denominator cells. This closes these stated fixture mechanics, not
the real-source integration or the full continuous historical SIM requirement.
An older captured bundle remains bound to its original package: the new runner
must consume it through a reviewed, pinned exact-byte/version bridge or its
original reader snapshot, never by rewriting its seal/fingerprint. No such
continuous historical integration or paid matched model run is claimed here.

## Exact legacy transfer into the current portfolio input contract

The separate create-only export at
`D:\Kairos\runtime\public-book-transfer-20261009-a\legacy-book-transfer.json`
ran once with the preserved B Python 3.11 `-I` environment. The exporter checks
the complete installed adaptive Python source roster against the independently
pinned B wheel before importing the old reader/auditor, checks actual imported
paths and kernel bytes, runs the old original-source audit/loader, and rechecks
sources and original receipt before its exclusive fsync write. It does not
import the current reader into B or rewrite the original capture.

The immutable E wheel, SHA-256
`25f4f642c4c2fccbb4d58ad013a342888895e9a38200a9b1e5484dee462b6b5d`,
is retained under `D:\Kairos\runtime\public-transfer-gates-20261009-e\dist`.
Actual Python 3.11.15 and 3.14.7 `-I` target checks verified all 65 installed
adaptive source files against that wheel. Independently supplied export,
wheel, script, original implementation and receipt commitments admitted exactly
1,280 canonical frames, all original segment coordinates and the unchanged
complete tape hash. Both targets created the same five-symbol `TapeBinding`.
The original receipt and raw-file SHA remained unchanged; the 3.14 check also
matched all five original segment-file hashes to the original receipt.

The current direct original reader still refuses the B capture with
`installed implementation changed; never reseal/adopt an old bundle`.
Only the explicit reviewed transfer path succeeds. Its result remains
`PASS_LEGACY_EXPORT_BYTE_CONSISTENCY_ONLY`: the B auditor owns the original
observed-source audit, while the current importer proves byte/DTO compatibility.
External commitments do not authenticate the publisher or grant source/risk
admission. No economics or order was executed.

| New artifact | SHA-256 |
| --- | --- |
| Exact legacy export | `3ee7883899571862eeae80ff8d9f2d852c8291c060a313cb952b18634469f7bf` |
| Standalone B exporter | `3532f17967da6f57b040d1d7b777cfecab90df411f8e81fcf00926f7a16fc656` |
| Complete unchanged book tape | `5294c07d5e06db6dcb7c8231154b497615e67d80207d2b7d194999ff1b7fd8ff` |
| Current portfolio input mapping | `11f229f33b700ed1a436f47b01de152329a9bbb98b3169d45c72b90232378a18` |

The [portable observation receipt](receipts/public-book-transfer-20261009.json)
records both actual target checks. Thirty-eight synthetic transfer tests and
the 69-test transfer/tape/portfolio regression check pass. They cover altered
commitments, DTO incompatibility, raw/native/mapping conflicts, complete segment
rollover, duplicate JSON keys, bounds, aliases and shadow source rosters; they
are not source authentication, full historical coverage or economic evidence.

The complete E installed-wheel suites passed 1,581 tests with four explicit
platform skips on each Python 3.11 and 3.14. Both used Python `-I`,
`--import-mode=importlib -W error`. Their separate final JUnit files are
`full-py311-strict.junit.xml` and `full-py314-strict.junit.xml`, reporting
314.081 and 244.807 seconds. All 65 installed adaptive Python files match the
retained E wheel. Development lint, formatting, locked offline resolution and
meta/static-link gates pass. Hosted CI is a separate published-source check.

The first E full suites are preserved as `full-py311.junit.xml` and
`full-py314.junit.xml`; each had one failure, 1,579 passes and four skips. The
failing test assumed the surrounding interpreter was not isolated, whereas the
stronger gate deliberately uses `-I`. The test now explicitly exercises both
non-isolated Python and isolated-but-not-private environment refusal. The
exporter's mandatory isolation check, script SHA, source/clock/coverage limits
and all implementation bytes are unchanged. No warning filter, skipped failing
case or relaxed source gate was used. The new V3 journal/driver integration is
not present in this E wheel and has no inherited gate claim.

## Historical source gap and causal creation boundary

A scoped read-only recheck of the fixed A/D pilot retained the earlier preflight's
recorded 129,600 one-minute bars and 270 funding rows on the declared archive
grid. The A ZIP/checksum pairs remain present; D is referenced through the
previously validated cache, not newly certified by a second full import here.
Official ZIP/checksum consistency does not supply historical BBO,
depth quantities, local historical delivery or all-in execution evidence. The
old incomplete 900-second price attempt is not resumed or replaced by this audit.

The existing CPI vintage extractor is already implemented and tested; it is
not an additional unfinished coding task. The retained two-vintage ALFRED
archive and semantic extraction remain narrower than accepted full MACRO
coverage. Three retained NEWS bodies do not form the required historical roster:
the current Gensler syndication response lacks independent exact-version
availability at the January 9 cut, the deleted SEC response is a tombstone, and
the House letter is after the fixed cuts. Earlier failed/limited source attempts
are preserved; none is retried merely to produce activity. See the existing
[preflight](HISTORICAL-CONTEXT-PREFLIGHT-2026-10-07.md),
[no-call receipt](HISTORICAL-PILOT-NO-CALL-2026-10-07.md) and
[implemented CPI semantics](HISTORICAL-PILOT-IMPLEMENTATION-2026-10-07.md).

The unchanged V2 hypothesis contract also requires its creation clock to equal
the native minute cut and all creation evidence to be captured by that cut.
A genuine closed-bar receipt arriving after the cut cannot be backdated to
satisfy this check. An old book transfer fixes package compatibility only; it
does not grant historical NEWS/MACRO admission, invent a contemporaneous candle
receipt or permit a later modern model response against already expired quotes.
Any future causal-creation correction must be separately versioned and retain
the original cut, anchor, parent identity, exits and predeclared validity rather
than relaxing or resealing an old plan on observed results.

Read-only provider documentation review identified possible external historical
book sources, not acquired or admitted data. The official
[Binance public archive schema](https://github.com/binance/binance-public-data)
describes klines and trades; those records are not executable bid/ask depth.
[Tardis Binance Futures documentation](https://docs.tardis.dev/historical-data-details/binance-futures)
describes recorded depth/bookTicker streams and free normalized CSV data for
the first day of each month. That free-day scope does not match the fixed May 19
and January 9 cuts. No account, subscription, key, paid endpoint, replacement
date selection or historical data download was used in this documentation check.

## Separate actual-creation contract V3

The new `hypothesis_v3` preserves the original technical/context parent and
splits price-origin `origin_cut_ms` from actual materialization `created_ms`.
An actual post-cut closed-bar receipt no longer needs to be backdated. The
policy still must be sealed by the original cut; validity stays original-cut
plus predeclared lifetime, and the original parent/reference/SL/TP/timeout/
trailing rules are retained. No V2 plan or old ledger is converted or resealed.

Context proposals require a distinct typed actual-creation assessment, binding
the supplied input, response, model configuration, direction and actual
requested/completed/captured clocks. No projected historical completion, paid
call or publisher authentication is inferred from these fields. The minimal
contract rejects creation at or after the first completed post-anchor minute;
it cannot silently discard an earlier stop/trigger. Its complete minute fold
starts at the origin cut, not the rounded actual creation time. Fifty-three
synthetic V3 checks pass on Python 3.11 and 3.14; 67 unchanged V2/bridge checks
also pass on Python 3.11. This closes a pure clock-contract defect, not the full
prospective integration.

Remaining implementation obligations are a separately versioned prospective
frame with actual knowledge clocks, exact raw closed-bar/finality receipts,
non-resetting multi-day horizon and a fixed four-arm continuous driver. The
[separate matched V3 journal](PROSPECTIVE-MATCHED-JOURNAL-2026-10-09.md) implements
atomic shared-source evidence with arm-bound reviews and checkpoint restart;
it does not close these source/driver obligations. The later
[V3 portfolio intake](PROSPECTIVE-PORTFOLIO-INTAKE-2026-10-09.md) checks exact
normalized originals, earlier WAITING observations, actual request/shared
availability and sealed origin routing. Its isolated installed-wheel checks
do not prove raw finality, a complete source set or the five-day horizon. A
strategy-blind response from the origin frame cannot become a review of later
sources/quotes the model never saw. A separately sealed held-context policy
or an actually later frame/review must explicitly resolve that difference;
retiming the old response is prohibited. The driver must retain the full source
denominator, select the earliest eligible receipt/quote deterministically and
account for model/feed expenses even on veto, errors, expiry and no-fill.
Shared physical spend and each arm's counterfactual costs must remain distinct.
These are open obligations, not an assertion that the fixed matched economic
comparison has run or that any source gap has been solved.
