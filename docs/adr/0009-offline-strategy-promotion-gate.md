# 9. Fail-closed offline strategy promotion gate

Date: 2026-08-17
Status: Accepted

## Context

Kairos can now run its historical strategy campaign locally before any real provider or exchange
API testing. Deterministic execution and green software tests are necessary, but they do not show
that a selected strategy generalizes or that live venue behavior is qualified.

Parameter selection and inspection contaminate the research interval. Rolling folds taken from
that same interval remain useful temporal diagnostics, but calling them out-of-sample would create
false promotion evidence. Promotion also needs reproducible source provenance, causal execution,
explicit liquidity and terminal-position semantics, and a gate that fails closed when evidence is
missing or internally inconsistent.

## Decision

The strategy-validation campaign uses these rules:

1. Freeze the selected candidate before promotion evaluation:
   `confirmation_bars=12`, `minimum_hold_bars=48`, and `minimum_confidence=0.67`.
2. Use official Binance Futures monthly 1m archives. Verify the published SHA-256 sidecar for
   each archive and the CRC of ZIP members. Inventory, source and checksum snapshots are compared
   at campaign start and end so a changing input cannot produce an accepted report.
3. Audit the 12-month research interval and the untouched July holdout. Missing archives,
   checksum failures, invalid rows, time gaps, incomplete coverage, or an upstream archive
   anomaly remain explicit fail-closed reasons.
4. Enforce causal execution: signals use closed data, become eligible at the first subsequent
   candle open, and consume a liquidity budget derived from the previous closed candle's volume.
   Record IOC attempts, partial fills, fill ratio and terminal liquidation evidence.
5. Treat rolling folds as post-selection temporal diagnostics only. They are not promotion OOS.
   Only untouched July is out-of-sample evidence for this frozen candidate.
6. Report actual historical funding as unavailable when it is unavailable. An assumed adverse
   funding scenario is useful sensitivity evidence but cannot satisfy the historical-funding
   promotion requirement.
7. Produce promotion readiness from validated, finite evidence. Any failed requirement yields
   `needs_revision` and `real_api_allowed=false`; a report is replaced only after the campaign
   and final input-snapshot checks complete.

## Recorded evidence

The frozen campaign recorded:

| evidence | baseline | stress |
| --- | ---: | ---: |
| 12-month research replay | -4.231727849843687% / 803 trades | -9.763199273155571% / 804 trades |
| untouched July promotion OOS | -1.075965871769744% / 69 trades | -1.5781050811020259% / 69 trades |

The untouched July buy-and-hold benchmark returned +6.828606504564661%, while zero of five
strategy symbols were positive. The promotion decision is therefore `needs_revision` with
`real_api_allowed=false`.

The blocking evidence includes:

- insufficient OOS trades;
- non-positive OOS return and expectancy;
- OOS benchmark underperformance;
- unavailable actual historical funding;
- non-positive sensitivity results; and
- upstream archive anomaly, gaps, or incomplete coverage.

## Consequences

- Real trading APIs remain disabled for this strategy. Backtest results must not be presented as
  live qualification, venue calibration, or production readiness.
- Strategy or parameter changes require a newly frozen candidate and genuinely untouched future
  promotion evidence. Re-labelling research folds as OOS is prohibited.
- The audited archives and frozen configuration make the current result reproducible, while
  snapshot guards prevent publishing a report from inputs that changed during the campaign.
- Risk and execution fail-closed hardening reduces unsafe behavior but does not close operational
  qualification. A durable execution journal, crash-safe TP/SL side-effect deduplication, live
  EVEDEX calibration, canary execution, observability and recovery exercises remain required.
