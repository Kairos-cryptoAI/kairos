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
read-only journal checks. Installed-wheel and hosted verification evidence will
be recorded after those gates complete, without another historical replay.

Still required before a new economic/model test: independently accepted causal
quote/context corpus with source continuity and missing denominators; an
explicitly sealed execution model/roster with actual-versus-modeled costs;
and a separately reviewed complete-system matched comparison. No old results
are retuned or merged. Paid models/feeds, EVEDEX/canary/LIVE, Docker PAPER,
primary PostgreSQL/leases/cursors and guarded recovery remain untouched.
`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
