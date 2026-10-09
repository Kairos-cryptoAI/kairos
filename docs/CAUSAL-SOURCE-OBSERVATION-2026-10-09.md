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
integration or paid matched model run is claimed here.
