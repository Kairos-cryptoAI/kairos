# Two-episode historical pilot: source-only preflight — 2026-10-07

## Current result

The owner confirmed reuse of the existing OpenAI credential. No new key was
created, no credential contents were loaded, and no secret was copied into the
repository or a new persistent environment file. The approved pilot retains
two episodes, at most twenty underlying paid attempts, no retries/escalation,
and a cumulative USD 1 ceiling intersecting the unchanged shared OpenAI USD 12
campaign ceiling. These are ceilings, not spending targets or source admission.

**Paid dispatch remains blocked.** No accepted exact-version NEWS/MACRO archive,
independently accepted acquisition coverage, or fixed required source roster
exists for these cuts. A current page, retrospective narrative, SHA, or a
caller-supplied `COMPLETE` flag cannot supply that proof. Required inputs cannot
be demoted to optional to make a model call possible.

Actual pilot paid attempts: **0**. Actual new model expense: **USD 0**.
Strategy generation and historical economics: **not executed**. No model
profitability, best strategy, observed historical model response, full-system
qualification, or successful historical trading result is claimed.

## Cuts fixed before candidate/model/economic inspection

The [living pilot roster](../development/adaptive_replay/historical-episodes-draft.json)
now fixes these four UTC minute-open boundaries. A uses calendar anchors; D
rounds the audit-only event anchors upward to the existing five-minute clock.
No earlier candidate can be transferred to a later cut. Original candidate
decisions bind that frame's last closed minute (`cut - 1 ms`). For the existing
adaptive default, eligibility is at the cut and expiry is `cut + 59,999 ms`.

| Episode | UTC cuts | Selection basis, not prompt data |
| --- | --- | --- |
| A, May 17–22, 2021 | May 19 00:00 and 08:00 | Fixed UTC calendar anchors |
| D, January 8–13, 2024 | January 9 21:15 and 21:30 | Audit event anchors 21:11/21:26 rounded upward to the native five-minute grid |

The modern [SEC January 12 account](https://www.sec.gov/newsroom/speeches-statements/gensler-x-account)
documents the January 9 event sequence, but is **later than both D cuts** and is
excluded as model input. Preselecting cuts using that audit record does not make
the record contemporaneous. Famous-event selection and possible model training
knowledge remain explicit contamination; this is not an unseen alpha sample.

One source/configuration identity and admitted model route remain unfixed for
actual execution. This source preparation does not nominate the adaptive
prototype, a daily baseline, or any previously tested strategy as a champion.
No family/threshold/cut replacement is permitted to manufacture a candidate.

## Fresh read-only shared-budget check

At **2026-10-07 12:28:23.550409 UTC**, a transaction with
`transaction_read_only=on` queried the already-running isolated shadow database.
The exact container was `kairos-shadow-gate-timescaledb-1`, Compose project
`kairos-shadow-gate`, database instance
`e5841a09-9fd4-42c1-870c-4d0ea14411d8`. Its identity matched the existing delivery
receipt. No container, migration, consumer, primary recovery, lease or budget
adoption/reset operation was performed.

Campaign `kairos-dev-qualification-v1`, provider OpenAI, micro-USD accounting:

| Budget component | USD |
| --- | ---: |
| Existing cumulative ceiling | 12.000000 |
| Historical off-ledger amount retained by the campaign | 0.001984 |
| Committed usage, 26 records | 0.040570 |
| Outstanding reservations, 6 records | 0.154624 |
| Total counted exposure | 0.197178 |
| Remaining shared headroom at this snapshot | 11.802822 |

This is a ledger snapshot, not invoice completeness proof or permission to
release ambiguous reservations. Each future attempt still requires atomic
reservation in the authoritative ledger and independent pilot attribution.
Previously committed/held usage is never cleared or reclassified as free.
The approved USD 1 pilot cap is additional, not a replacement USD 12 budget.

## Market source scope

The Jan 2024 cached monthly archives actually passed `load_window` and
`validate_replay_inputs(fixture_only=False)` for **all five symbols**. This was
source-only validation: no strategy, model, fees-based ledger or economic run.

- Original evaluation interval: January 8 00:00 through January 13 00:00 UTC,
  end exclusive; **36,000 original five-symbol minute slots**.
- Complete supplied warmup/exit horizon: January 5 through January 14 00:00 UTC,
  end exclusive; **12,960 bars and 27 funding events per symbol**.
- Total supplied rows: **64,800 full-kline bars and 135 funding events**.
- Full-kline parsing, official checksum/ZIP checks and exact grid/tail validation
  passed; this is not the earlier field-specific price-only source acceptance.
- A per-frame resolver must receive its separately bound, at-most-5,000-bar
  causal prefix, not the entire 12,960-row parent archive. Future execution
  bars/funding never enter the model prompt.

May 2021 archives were absent in the original local cache. After offline tests
and installed-source verification, the **single actual bounded acquisition
passed** in **35.4652432 seconds**, with twenty free official archive/checksum
GETs and **9,569,808 downloaded body bytes**. Those are public-data GETs, not
twenty model attempts; actual paid model attempts remain zero.

- Original evaluation: May 17 through May 22 00:00 UTC, end exclusive.
- Full warmup/exit horizon: May 14 through May 23 00:00 UTC, end exclusive.
- Each of BTC/ETH/SOL/BNB/XRP: **12,960 full-kline bars, 27 funding events,
  zero bar gaps**, with official checksum and ZIP/member verification.
- The new cache holds ten ZIP/checksum pairs and one sanitized source summary;
  the original Backtest cache was not populated or changed. Backtest remains
  clean on `main`, matching its local `origin/main`.
- Actual source summary (retained locally, not a repository dependency):
  `D:\Kairos\runtime\historical-pilot-market-20261007-a\source-summary.json`.
  SHA-256: `d675927847971ab73cb6bc36f2a36c09584d7967fe4979a36db8d33a56dcd507`.
  State: `SOURCE_INPUTS_VALIDATED_ONLY`; provider calls zero; strategy/economics
  and trading authority false. Original files and summary are preserved.

Both selected episodes now have accepted **market-input validation only**:
129,600 supplied full-kline bars and 270 funding events across the two complete
warmup/tail horizons. This does not accept NEWS/MACRO, historical news availability,
model costs, a strategy, observed fills or EVEDEX liquidity. There was no second
download, retry, gap filling, cache overwrite, strategy generation or economic
rerun.

## Exact-context acquisition findings

- [China Banking Association May announcement](https://www.china-cba.net/Index/show/catid/15/id/39462.html):
  direct page retrieval timed out; publication-only search metadata did not
  establish an exact body, original version or conservative availability clock.
  One bounded Wayback availability request returned **HTTP 429** without retry.
  The CDX query for May 17–22 returned **HTTP 200 and zero rows**. This records
  failed acquisition, not proof that the original news did not exist.
- Original January 9 public X leads did not yield accepted version payloads:
  the Gensler lead returned an empty extracted page and the SEC lead returned
  404. No paid X API, authentication bypass or fabricated tweet body was used.
- The [SEC January 10 approval order](https://www.sec.gov/files/rules/sro/nysearca/2024/34-99306.pdf)
  was accessible and dated, but is **future content at both January 9 cuts**.
  The January 12 account is retrospective; neither is eligible context there.
- The January 10 congressional letter lead timed out. No exact-version NEWS
  payload or MACRO vintage/coverage was accepted by any of these probes.

All twenty symbol/cut combinations therefore remain context-source blocked.
Unknown coverage is not known empty coverage, `QUIET`, a model abstention, or
permission to omit original candidate/minute rows. The entire original windows
and explicit zero-cost scheduled no-call reasons remain required in any later
replay. No independently generated proposal route is evaluated by this work.

## Execution and continuation boundary

Even after source admission, a direction/review response is not a filled trade.
The unchanged 60-second adaptive lifetime plus any positive modeled response
delay leaves the next `STRICT_MINUTE_OPEN` quote after expiry. Keep no-fill and
incurred cost; do not select zero delay, extend expiry or invent intraminute
execution to show profit. Transaction prints are not historical BBO/our fills.

The next admissible step is exact-version payload and coverage acquisition and
independent acceptance for a fixed required NEWS/MACRO roster. Then freeze one
strategy/configuration and a budget-admitted route before candidate/model/economic
inspection. Current inaccessible sources do not authorize dropping a system
layer, synthesizing missing news, or spending on retrospective summaries.

Trial 15, V4/V5 plans/ledgers, dependency pins, release manifest, runtime primary,
venues and UI remain unchanged. No blind result was read or disclosed.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.

## Engineering verification

The installed non-editable wheel passed **508 tests and one skip on each of
Python 3.11 and 3.14**. The single skip is the test symlink creation unavailable
on this Windows host; portable path and create-only guards were still exercised.
The 17 new acquisition cases use synthetic offline archives/injected HTTP,
never actual provider observations. Two additional plan tests retain the exact
cuts/caps and confirm that user approval does not make an unadmitted plan
executable. Ruff check/format, unchanged locked dependencies, source/wheel build
and the meta static/Markdown-link gate passed.

Before the actual acquisition, its source and installed module SHA-256 both
matched `f2608e9b1725ee70041bdd0a35abeb8ff606ea63328e2276ffc4798777b2ecdd`.
No existing acquisition process was present. An actual CLI call without
`--fetch` returned `FETCH_NOT_REQUESTED`, `network=false`, `output_created=false`;
the intended output directory still did not exist. No key was needed for this
public source-only check. Final publication additionally requires the exact
GPG-signed main commit's GitHub CI, not only these local checks.
