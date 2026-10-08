# Research quote bytes and supplied simulated-fill feasibility

Date: 2026-10-09 Europe/Moscow. Separate additive engineering work after the
[durable hypothesis journal](HYPOTHESIS-JOURNAL-2026-10-09.md), not a new strategy,
economic experiment, campaign enrollment or trading admission.

## Implemented boundary

`development/adaptive_replay/adaptive_replay/quote_capture.py` retains exact
immutable UTF-8 payload bytes and verifies their SHA-256 before parsing. The
payload is bounded to 8,192 bytes. Duplicate/unknown/missing keys, BOM, invalid
UTF-8/JSON, coercion, nonfinite/nonpositive values and locked/crossed books fail.
The exact research schema is `kairos.development.bbo-payload.v1`, with fields:
`schema_id`, `timestamp_unit` (exactly `ms`), `source_id`, `symbol`, `event_ms`,
`bid`, `ask`, `bid_quantity`, `ask_quantity`. Quantities are base-asset units.

This is an explicitly new **Kairos research wire schema**, not an invented claim
about an official exchange message. No converter from candles, prints, marks or
native summarized market messages exists. No feed is started or downloaded.
Native RecordedTopNBookFrameV2 retains raw text/hash but does not itself prove
that raw fields match normalized levels and clocks; it is not silently admitted
as this source. Actual source adapters and authenticated capture coverage remain
unimplemented and unaccepted.

The capture receipt separately binds original bytes, parsed quote/quantities,
caller-supplied receive/capture/TTL clocks and evidence classification. Receipt
consistency is not publisher authentication or independent chronology proof.
Admission checks the exact hypothesis source, symbol and evidence class, the
required causal boundary, capture availability and event-anchored age. Delayed
receipt/capture never refreshes an old event deadline. Integer/float-equivalent
raw prices normalize to floats; the issuing quote must still match the retained
EntryQuote digest exactly, not merely Python numeric equality.

`fill_feasibility.py` freshly opens the retained JournalSeal and audits its
complete original source binding, typed plans, chronology, hash chain and fold.
It does not trust a caller-created snapshot, issuing receipt or copied provenance
metadata. The supplied entire candidate must match the unique journal-issued
candidate, with reconstructed native identity and complete original ExitPlan.
The issuing capture must match the retained normalized quote digest. Raw bytes
are supplied separately; the existing journal does **not** acquire a new raw-byte
column, and this adapter does not claim their prior durable publication.

For the execution-side snapshot and one supplied hypothetical fill, checks are:

- Exact arm, parent, intent, symbol, side and original protection identity.
- Original inclusive entry deadline; no renewal by a later quote or capture.
- New execution quote event at/after candidate issue, capture at/before fill,
  and original source/policy freshness bounds. Older issuing BBO is not reused
  as a newer execution snapshot.
- Exit-side quote has not breached the original stop; original directional
  confirmation still holds at the executable side.
- Fill strictly inside original stop/target and before original trailing
  activation, preserving trailing distance and holding duration unchanged.
- One supplied quantity no larger than the same capture's executable top-side
  quantity; missing quantity is not interpreted as infinite liquidity.
- Conservative LONG at/above ask and SHORT at/below bid; no assumed midpoint or
  price improvement. Current quote spread and adverse displacement from its
  executable side use unchanged fixed planning caps (2 bps / 1 bp respectively).
- Frozen ATR bounds when present, maximum stop distance, planning cost headroom
  and net reward/risk are rechecked at the supplied fill price.

The cost assumption remains the existing fixed 20 bps planning model, including
fees, spread, slippage, uncertainty, carry and latency components. It is not a
measured venue/model/feed expense or a new complete-system net result. Source
and execution snapshot clock gaps do not establish continuous path integrity.

## Authority and preserved evidence

Success is `SIMULATED_CHECK_ONLY`, with `risk_authority=NONE`. It is neither a
RiskTradeDecision nor a fill acknowledgement. Missing/invalid causal evidence
stays unavailable; operational incompatibility stays refused. Structural/schema
or journal integrity conflicts raise and do not reconstruct/adopt missing data.
No Portfolio.admit, sizing, position, order payload, dispatch, execution ledger,
retry, parameter search or CLI runner is introduced. Checking twice does not
reserve/consume liquidity twice or authorize repeated fills. Partial execution,
multi-fill accounting and protective order placement are not qualified here.

Exact-byte validation and top-side quantities cannot establish authenticity,
continuous tick/depth coverage, actual exchange execution or safe SL/TP races.
Native runtime still refuses trailing. This change does not enable that runtime
path, paper services, recovery consumers or LIVE. Risk caps remain 0.25% per trade
and 1% aggregate open risk, with no required daily trade count.

Old scenarios/v2 engines, evaluator, journal implementation, Trial 15/V4/V5,
frozen plans/ledgers/results, release manifest, dependency pins and locks remain
unchanged. Because journal binding inventories every installed research module,
these additions intentionally require a **new** source identity for future
fixtures/experiments. Previously sealed journals refuse this changed inventory;
they are not resealed, migrated, deleted or rescued.

## Verification scope and next admission

Only synthetic offline fixtures are used. Verification covers exact bytes,
source/clock boundaries, restart and copied-candidate conflicts, LONG/SHORT
protection/capacity/deadline boundaries, all refusals/unavailable states and
read-only journal checks. There are 147 new cases: 52 capture cases and 95 fill
cases. Full fresh non-editable installed-wheel suites passed on Python 3.11.15
and 3.14.7: 1,138 passed and two existing platform symlink-fixture skips in each.
The final three added cost/ATR cases then passed separately in both environments
(three passed, 92 deselected). No new skips or historical rerun occurred.

Ruff lint and format (120 files), unchanged lock verification, wheel/sdist build,
Meta static/Markdown/checkout-regression gates and git diff checks passed.
Environments/builds are retained in
`D:\Kairos\runtime\quote-fill-admission-build-20261009`. Both installed copies
match checkout bytes:

- `quote_capture.py`: `dfff35796e1d9f0265e8521cd392d4af89df30d6c2d6c90425ea81f3fe0fe365`.
- `fill_feasibility.py`: `7fe5011e661cc84abb3d0143594c95f8d9797b931163d45ca160d48bcd983c57`.

The implementation and scope are GPG-signed main
`a24b0e2095b6e7e2a93a324ee179d368d2a00d8e`; local verification and GitHub both
confirm a valid signature. Original v1 scenario/bridge/comparator, v2 hypothesis/
bridge and journal byte hashes still match their prior receipts. Strategy and
Backtest main remain clean and unchanged; release and dependency identities
were not edited. This verification-only document does not change source or
grant campaign enrollment, quote authenticity, trading authority or readiness.

The complete implementation/scope revision passed all hosted gates:

- [Adaptive installed-wheel fixtures](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37850318697):
  1,143 passed, zero skips, in each Windows/Linux x Python 3.11/3.14 job,
  including all 147 new cases and the existing platform-dependent cases.
- [Meta validation](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37850318707): passed.
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos/actions/runs/37850317686): passed.

Still required before a new economic/model test: independently accepted causal
quote/context corpus with source continuity and missing denominators; an
explicitly sealed execution model/roster with actual-versus-modeled costs;
and a separately reviewed complete-system matched comparison. No old results
are retuned or merged. Paid models/feeds, EVEDEX/canary/LIVE, Docker PAPER,
primary PostgreSQL/leases/cursors and guarded recovery remain untouched.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
