# Retained REST closed-bar evidence — October 9, 2026

## Delivered engineering

The additive `closed_bar_evidence_v3` fold binds exact retained REST bodies,
complete attempt numbering and predecessor hashes to an independently retained
receipt checkpoint. It includes HTTP errors, malformed pages and no-response
attempts in its denominator. Canonical receipt hashes are recomputed from all
fields; moving a processing or persistence clock without its original receipt
does not create usable candle evidence.

The fold compares every field of the pinned Quant `ClosedKline`, requiring two
identical native observations before contiguous promotion. A changed candidate
resets its count. A gap remains pending; filling its predecessor records the
actual later promotion clock instead of backdating availability. A changed
already-promoted native row fails closed immediately. Trade count and the REST
array's ignored twelfth field remain in both original rows and response bodies,
but are not incorrectly added to native `ClosedKline` equality.

The reviewed native reference is Quant revision
`927f5730d09383736c1dfc7dc5c400b06851019f`, collector file SHA-256
`05198d41b53ef8a1ad1d4f4a0ae8a2ccb674470ba78db02595c48c5ffed678b6`.
This is not a claim of identical behavior for every parser or capacity edge:
the binding requires exactly twelve fields, rejects a malformed complete page,
and fails closed at explicit pending/candidate bounds. A caller-supplied restored
close watermark filters overlapping older rows; it is not a verified original
warmup history. All request, response, body-fsync and processing clocks remain
caller attestations, not independent historical clock authentication.

## Installed-wheel checks

The fresh immutable E snapshot contains 70 adaptive Python modules, 85 test
files and three configuration files. Its exact non-editable wheel SHA-256 is
`defdf77ffe561b28fb32915f38b4256f5fc31859570d50bfb13732c8a61379b8`.
All 70 installed module names and byte hashes match the wheel and retained
sources on each private interpreter. Offline lock, Ruff and format checks pass.

| Focused installed suite | Passed | Failures / errors / skips |
| --- | ---: | --- |
| Python 3.11.15 | 16 | 0 / 0 / 0 |
| Python 3.14.7 | 16 | 0 / 0 / 0 |

The suites use Python isolation, importlib loading and warnings as errors.
The [machine-readable receipt](receipts/closed-bar-evidence-gates-20261009.json)
binds the exact source, tests, wheel and JUnit hashes. The initial invocation
with a missing run directory did not execute tests; it is retained as a setup
failure, not relabelled as a test pass. No full E suite is claimed. The preceding
[storage gate](PROSPECTIVE-STORAGE-2026-10-09.md) remains its own complete D suite.
The unfinished horizon and four-arm driver are excluded from this E snapshot.

## What is still required for full points 1–3

This pure offline fold performs no HTTP request, producer integration or source
authentication. It supplies neither complete historical BBO/NEWS/MACRO nor an
accepted five-day financial comparison. Prospective native capture/processing
integration, accepted historical coverage, complete financial horizon and the
fixed four-arm driver remain separate requirements. Modern captures cannot be
backdated into 2021 or 2024 evidence; unavailable sources/costs stay unavailable.

No paid model call, primary recovery, service start, order, winner or blind
credit follows. Trial 15 and V2/V4/V5 evidence are untouched. All four readiness
flags remain false, `STRATEGY_POLICY=REJECT_ALL`, and UI remains deferred.
