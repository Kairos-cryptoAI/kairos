# Historical pilot: bounded archive continuation, no paid dispatch

## Outcome

The owner instructed continuation. The conservative interpretation preserved
the same A/D episodes, all four cuts, twenty underlying attempts, zero retries
and the cumulative USD 1 pilot ceiling inside the existing USD 12 OpenAI budget.
No episode substitution, optional-source demotion or weaker source gate was
assumed. The prior [no-call preflight](HISTORICAL-PILOT-NO-CALL-2026-10-07.md)
and its nine-lead capture were not repeated or rewritten.

New bounded archive searches did not obtain acceptable NEWS proof. A **new,
successful, small first-party ALFRED raw vintage download** was retained. The
[local companion budget helper](HISTORICAL-PILOT-BUDGET-2026-10-07.md) was also
implemented and independently reviewed; it is not a paid dispatcher or shared
budget adoption. No model/provider request, trading operation, secret read,
primary/runtime recovery or shared budget mutation occurred.

## Fresh NEWS archive checks

The public Hugging Face dataset viewer for `brian-learns/cdx-cc-news` returned
HTTP 200 metadata: `default` configuration, `year_2021` and `year_2024` splits.
Observed response sizes were 895 bytes for splits, 78,587 / 47,149 bytes for the
two first-row responses. Schema fields were `Surt`, `capture_time`, `url`, `mime`,
`status`, `digest`, `length`, `offset`, `filename`; sample rows were unrelated.
This is index metadata, **not** an accepted article/WARC capture.

Two new targeted searches (NIFA and the Xinhua May-18 URL prefix) were attempted
inside one tool execution. That outer execution completed without returning the
nested HTTP result or shell session ID. Both results are `UNKNOWN`: no HTTP
status, hit, empty-result, timeout or absence conclusion is inferred. No retries
or massive dataset/WARC download followed. A later relevant-process check found
no remaining process with the exact dataset marker; it did not start one.
Metadata body hashes were not retained, so this observation is not promoted into
immutable acquisition evidence.

A separate independent review made four new bounded queries: exact SEC-post
archive search, official BLS correction-policy search, an exact-URL Wayback CDX
query for January 9 21:11--21:30 (limit ten), and BLS errata. It obtained no exact
pre-cut original SEC-post body/version proof. Inaccessible CDX/errata responses
are not absence evidence; mutable third-party references are not substituted for
the required primary evidence.

The existing Gensler singleton-version response remains a lead, not proof of
account-feed completeness. Late SEC/House incident reports may audit identity,
but their later conclusions must not label the 21:15 account announcement as
false or compromised in its historical prompt. The additional unauthorized
post cannot be silently erased from a purported complete feed.

## One actual ALFRED download

Source: [official public CPIAUCSL download form](https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL).
ALFRED [documents historical vintage-date downloads](https://alfred.stlouisfed.org/help/downloaddata),
including returned vintage columns and README metadata. Two successful bounded
form inspections established its public fields; no credential or cookie was
required. The single subsequent data-download POST used:

- Series `CPIAUCSL`; units `lin`; monthly observation range April 2021--November 2023.
- Vintage dates `2021-05-18 2024-01-08` (each day before the respective cuts).
- Output type 2: observations by vintage date, all observations; zipped CSV.

Actual request: `2026-10-07T15:19:02.466Z`; body observed:
`2026-10-07T15:19:03.251Z` (18:19:02--18:19:03 Europe/Moscow), 785 ms.
HTTP 200, `application/zip`, **2,185 raw bytes**, one request, zero retries.
The twenty-second transport bound is cooperative, not a hard process watchdog.
The exact URL, TLS/redirect and declared/actual byte limits were checked.

Artifacts are retained at `D:\Kairos\runtime\historical-macro-raw-20261007-a`:

| Artifact | SHA-256 |
| --- | --- |
| `request.json` | `7627d8a1292b6843ee94e6de48cfe88992e4e52a7ee2b3922a257e2f58c8d3d5` |
| `receipt.json` | `6f2aff0b2f8742b62eaf05292b6f464bc9c7d6b0b535448d3ebf77f3ed13418a` |
| `alfred-cpiaucsl-vintages.raw` | `a8ebaf703c3db79ed0997f083b4a488f3d7302db46afed666ede82e41e8835a4` |
| ZIP member `README.txt` (4,166 bytes) | `dc393de0cbb07585fc56dd983b9f754753e563f4fcf32ecd7483abd6cc595938` |
| ZIP member `vintages_starting_2021-05-18.csv` (700 bytes) | `a66a2035c33d36e51a64a47da9200cb6c4d48c2e8aa9d0da1999a27f7b94b034` |

The ZIP was inventoried/read in memory, not extracted to filesystem paths.
Independent local audit verified raw/member hashes and these contents:

- README specifies both requested vintages, BLS source, monthly frequency,
  seasonally adjusted values and index units `1982--1984=100`.
- The CSV has 32 monthly rows and exact columns `CPIAUCSL_20210518` and
  `CPIAUCSL_20240108`.
- April 2021 is `266.832` in the May-18 vintage but `266.670` in the January-8
  vintage. This concrete revision is why the later column cannot replace the
  earlier historical input. November 2023 is `307.917` in the January-8 vintage.

These are archival observations, **not strategy returns, forecasts or model
decisions**. Capture state is `RAW_VINTAGE_DOWNLOAD_CAPTURED_UNADMITTED`;
`coverage=UNKNOWN` and `admitted_to_prompt=false` are preserved. No
`HistoricalArchive` or COMPLETE source claim was constructed. A future admitted
extractor must isolate the correct vintage column, validate declared bounded
metric scope/completeness and observation/release freshness, and keep modern
README text/capture metadata out of prompts. Daily vintages cannot prove an
intraday publication time or a historical local Kairos receipt.

## Code and verification

Capture-module SHA-256 before/after actual execution:
`ed9c73d73712bc6273ecf55965e436bb2c479f55f9f4f1f186ec7975cf677f05`.
Unchanged pilot-draft SHA-256:
`d9347eeca568f6b8fc98a75645ffe484e27df2ce3cd84415b97f8b554d12e497`.
Final local-cap-module SHA-256:
`de80a26e41b474462eab7db256bdb32d57c219abf6d09f9b0ddac8f327e324fb`.
Both Python 3.11 and 3.14 noneditable installed modules match these source bytes.

Full offline suites: **596 passed, 2 skipped** on each Python version (66.37s /
61.94s). Both skips are platform-dependent symlink creation tests on Windows.
Ruff lint/format, locked dependency check, wheel/source build, static manifest
runner and local Markdown-link checks pass. Dependencies/pins/locks were not
changed. Independent deep review accepted the final companion budget and raw
capture boundaries. These tests do not execute the historical economic pilot,
call a provider, read blind performance or qualify the final adaptive system.

## Remaining actual prerequisites

1. Acceptable primary NEWS version/availability and bounded-coverage evidence
   for the unchanged cuts. This remains unresolved.
2. A reviewed semantic MACRO extraction/admission from the retained vintages;
   successful raw download alone is not that admission.
3. Exact candidate/route/source-set admission and one native zero-retry paid
   dispatcher, bound to a single local cap identity and the existing authoritative
   PostgreSQL budget after fresh identity/headroom verification.

No paid or economic replay is claimed complete. Model cost in this continuation
is USD 0; no production budget ledger was initialized. Existing readiness remains
false/`REJECT_ALL`; Trial 15, V4/V5, frozen evaluators and primary data are untouched.
