# Causal historical context and retrospective review bridge — 2026-10-07

## Delivered engineering boundary

The user's next direction is to connect source-bound inputs, then emulate
historical strategy plus model review on preselected key episodes. This change
adds an isolated **1m historical reconstruction path**, not a conversion of native
campaign observations into the older 5m matched roster. Existing default system
API, frozen campaigns, native transport, strategy policies and budgets are intact.

- [Historical context](../development/adaptive_replay/adaptive_replay/historical_context.py)
  imports externally hash-pinned, bounded canonical JSON. NEWS/MACRO versions
  retain original publication bounds, exact-version availability, referenced event,
  realized macro-vintage time, actual capture, extraction/raw-content hashes and
  explicit availability proof classification. Unknown revision/availability is
  not an original version. Metadata-only pages are unavailable, not known no-news.
- [Closed-history resolver](../development/adaptive_replay/adaptive_replay/historical_bars.py)
  verifies the complete supplied bar tuple, exact minute grid and anchors, then
  exposes only its closed causal prefix. It never downloads/interpolates, fetches
  a reference, fills a gap or exposes future execution bars/funding in a prompt.
  Prompt bars expose OHLC only: volume/taker placeholders cannot masquerade as
  observed features without a separately qualified field profile. All capture
  clocks must follow realization of the supplied source artifact.
- [Historical review adapter](../development/adaptive_replay/adaptive_replay/historical_replay.py)
  binds source views and that exact bar prefix to an unchanged candidate, closed
  1m anchor and separately later context cut. It checks the complete five-symbol
  minute denominator against replay bars. No native intent/receipt ID is rewritten.
  The caller supplies original development `SleeveIntent`, not a forced conversion
  of native campaign contracts. Strategy source/configuration is one fixed account
  identity, but generator authenticity/provenance remains independently unqualified.

As-of selection admits exact content versions only at their conservative
availability/publication upper bound, inclusive at the cutoff. Date-only metadata
cannot sneak in at the beginning of its date. Latest **eligible** version wins;
post-cut corrections do not replace earlier news or revise macro vintages. News
can announce a future event; its referenced event time is not its knowledge time.
Realized macro measurements must already have occurred. Scope/TTL is source- and
symbol-specific. Unknown coverage cannot become an empty source. Complete empty
coverage is a separate caller-attested source observation, not every world's news.

Archive/coverage hashes are audit-only. Earlier prompts contain only causal bars,
selected exact payloads, unchanged candidate, declared source state and clocks.
Later archive membership, capture dates, whole-tape/ledger hashes, event labels
and exit outcomes do not enter them. Source text is untrusted data, not execution
instructions. The bridge itself has no retrieval or provider tools.

## Modern calls and hypothetical historical economics

`RetrospectiveReview` retains actual modern request/response/cost-observation
clocks, exact model/configuration, prompt and raw-response hashes, parsed
`ALLOW/VETO/DEFER`, failures, no-call reasons and known/unknown expense. These
records cannot become `OBSERVED_POINT_IN_TIME` historical provider receipts.
Only OpenAI is supported; this grants no paid-call or budget authority.

Actual requests must follow materialization of the prompt's selected source
versions, accepted coverage and bar artifact. One source/TTL roster and one full
archive are fixed across the episode, not changed per winning/losing candidate.
The entire execution prefix/tail and funding grid are independently validated;
duplicate rows, mismatched horizons and missing tail bars fail before accounting.

`evaluate_historical_review` explicitly projects a preregistered scenario delay
and each known modern expense onto a hypothetical historical account. Original
eligibility/expiry/SL/TP/holding time remain unchanged; a delayed reply cannot
force the baseline fill time. Selected original source views are rechecked for
TTL at the modeled quote; no later news refresh is allowed. An empty view also
expires. Failure, refusal and no-fill preserve cost; explicit no-call preserves
zero call cost without fabricating inference completion. Missing response or
unknown model expense nulls the entire model path, not just an inconvenient row.
Unavailable strategy slots make all accounts incomplete, not zero-trade evidence.

Three independent accounts reuse `COMMON_COST_RISK_V1` and the existing engine:
strategy-only, context-review and the same timing/cost control without review
content. The latter also removes operational error-gating, so its delta is not
pure content alpha. No trade quota or positive standalone-PnL admission rule.
Risk stays at most 0.25% per trade and 1% aggregate open risk with existing
notional/leverage limits. Original candle/proxy/funding limitations remain.

Actual modern research expense is reported separately from projected historical
account debits. One hypothetical account is not a second real provider invoice.
Unknown feed expense leaves recorded all-in net null; recorded expense still
does not prove invoice completeness or unrecorded infrastructure cost. Native
observations transport and the existing four-/six-path API remain untouched.
This review bridge does not implement independent LLM-generated proposal mapping.

The complete input roster is bounded to 100,000 frames, 14 days, 5,000 bars per
causal prefix, 2,000 archived versions, 16 MiB per archive and a single-process
15-minute validation/replay deadline. These are fail-closed resource guards, not
permission to restart earlier resource-closed source attempts. No economic run
or modern model invocation was executed by this work; only offline fixtures.

## Reproduction and accepted input requirements

Canonical create-only export returns a checksum to record independently:

```python
from adaptive_replay.historical_context import export_archive, read_archive

# archive contains independently reviewed exact versions and coverage receipts.
sha = export_archive(new_path, archive)       # refuses overwrite
archive = read_archive(new_path, sha)         # import validates exact bytes
```

Inspect an already saved transport from an isolated installed-wheel directory:

```powershell
python -m adaptive_replay.historical_context `
  --input 'D:\Kairos\runtime\accepted-historical-source.json' `
  --expected-sha256 '<independently-recorded-sha256>'
```

The sanitized CLI reports hashes/counts and false authority, not raw source text,
keys or model rationale. It never opens source URLs. `HistoricalFrame` supplies
safe prompt bytes; actual modern review records bind its exact `prompt_sha256`
and `frame_id`. The historical economic adapter accepts only a complete roster,
all incurred costs and explicit scenario timing, never selected winners only.
Input hashes validate bytes, not archive authenticity, source entitlement,
exhaustive acquisition, model/provider invoices or causal strategy production.
These still require independent acceptance. No saved historical payload archive
has been accepted, and no real model/economic result has been obtained here.

## Proposed episode source preparation, not an executed experiment

The separate [draft roster](../development/adaptive_replay/historical-episodes-draft.json)
contains four source-preparation windows, audit-only labels and two fixed
calendar-offset controls per episode. It is deliberately **not executable**:
the final economic protocol, exact sources/coverage, strategy and budget remain
prerequisites. Controls are not silently declared quiet; overlaps, other events
and missing sources must be retained, not replaced after looking at returns.

- May 2021: the [China Banking Association announcement](https://china-cba.net/Index/show/catid/15/id/39462.html)
  is a source lead, not an accepted content-version/time receipt; root retrieval
  did not establish its exact body/time. Venue-level bars, not a hindsight cause
  claim, must define the price episode.
- Terra: the [official first halt](https://x.com/terra_money/status/1524785058296778752)
  and [second halt](https://x.com/terra_money/status/1524935730308456448) are leads;
  their payload/time remained inaccessible in this investigation. The
  [LFG audit published in November 2022](https://www.lfg.org/audit/LFG-Audit-2022-11-14.pdf)
  is later evidence, never a May model input.
- FTX: use the [contemporaneous court docket](https://restructuring.ra.kroll.com/FTX/Home-DocketInfo)
  and original announcements with verified first availability. The
  [SEC December 2022 release](https://www.sec.gov/newsroom/press-releases/2022-219)
  is retrospective to the November episode, not pre-event news.
- ETF: the [SEC January 10, 2024 approval order](https://www.sec.gov/files/rules/sro/nysearca/2024/34-99306.pdf)
  is a primary dated document, not proof of local receive or precise first-public
  time. Preserve the prior false-headline confounder rather than selecting only
  the eventual correct announcement.

"Each news item" means every item/version inside a predeclared qualified source
roster and acquisition interval, not an unprovable archive of all world news.
Missing/blocked source coverage must remain explicit. Current web versions and
retrospective event summaries do not prove content existed before a chart cutoff.
No copyrighted full news corpus was downloaded or inserted by this preparation.

Modern models may already know these famous historical outcomes from training.
Restricted prompts, entity/date masking and "do not use hindsight" instructions
do not prove its absence. Reports always retain
`historical_model_observation=false`, `training_contamination_excluded=false`,
`representative_sample=false` and `blind_campaign_enrolled=false`. Results would
be conditional developmental stress diagnostics, not unseen predictive alpha.
No selected-event annualization or compounding across omitted dates is allowed.
Actual forward evidence and existing independent blind/venue/security/arming
gates remain necessary. All trading readiness is false; policy is `REJECT_ALL`.

## Verification

Focused tests exercise exact-version/canonical import, late corrections, date
precision, unverified body/coverage, future announcements versus realized macro,
symbol scopes, known empty coverage, source TTL, exact bar clocks/prefixes,
future-input noninterference, unchanged candidates, 1m denominator, modern versus
projected clocks, failure/refusal/no-fill expenses, unknown costs, fixture
isolation, forged clocks and false observed relabelling. Full installed-wheel
verification passed **490 tests on each of Python 3.11 and 3.14**, including 81
new historical tests. Ruff check/format, locked dependencies, source/wheel build
and the meta static/Markdown-link gate passed. All four installed module hashes
match the reviewed source. A second independent causal review found no remaining
blocker in this engineering scope after corrections to materialization clocks,
fixed source/configuration identity, full input integrity and no-call reasons.
The workflow requires the same offline gate on Windows/Linux and both Python
versions; publication acceptance additionally requires green exact-commit CI.

No paid API, exchange, database, Docker/recovery, consumer, trade, frozen research
ledger or readiness mutation is part of this change. Dependencies/locks and
source manifest pins are unchanged; UI/UX remains deferred.
