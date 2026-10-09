# Original funding settlement-price gap — October 9, 2026

## Actual observation and scoped conclusion

The exact fixed-window public observation made **one unauthenticated GET** for
BTCUSDT, May 17–22, 2021 (five entry days plus the exit tail). HTTP 200 returned
a complete 2,020-byte body containing all eighteen expected funding events.
Their symbols, numeric rates and original exchange calculation milliseconds
match the retained monthly archive exactly. **All eighteen `markPrice` values
are empty strings, not numeric zeros.** No usable settlement price was supplied.

The presealed collector stopped at that first validation failure. The remaining
nine symbol/window queries were **not attempted**. This does not establish their
response quality, a global archive absence, or why the first response omitted
prices. No retries, redirects, credentials or paid provider requests occurred.

The unchanged native intent, result, child receipt and complete raw body are
bound by the [portable receipt](receipts/original-funding-settlement-gap-20261009.json).
Actual request times were 2026-10-09 07:15:16.574491–07:15:17.148361 UTC.
They are retrieval wall times, not historical local receive evidence.

## Independent offline verification

The exact original response was reconciled on both isolated Python 3.11 and
3.14 against the immutable S2 source cohort. All 634 retained source-file
identities were verified before and after each analysis. The loader scanned
the complete 93-row May calendar, verified original ZIP/CHECKSUM/CSV/calendar
identities, and refused the actual empty-price body with
`bounded original Decimal string required`. Both analyses returned exit zero:
that verifies the expected refusal, **not source or financial acceptance**.
The analyses made no network or subprocess calls. The separate source-focused
S2 fixture gate has 57 passes on each Python version; it is not an installed
release gate or an actual financial simulation.

The original response remains byte-identical. No candle, entry quote, nearby
mark, rounded calculation time, zero-rate proxy or assumed price replaces the
missing original settlement price. Unknown funding cannot silently become
zero cost in a financial result.

## Preserved failures and corrected interpretation

The earlier R collector stopped in preflight before any network request:
the prepared May input-receipt path incorrectly referred to the January
scenario. R's original plan and failed result were preserved. A separate R2
clone pins the correct original May receipt; only R2 made the one GET above.

The first W offline analysis also failed before producing an accepted receipt:
Decimal parsing of an empty string raised `decimal.InvalidOperation`. W's
script and failure note are preserved. The separate W2 analysis explicitly
distinguishes missing strings from numeric zero and records the exact loader
refusal. A preliminary PowerShell decimal coercion had classified the empty
strings as zeros. That interpretation is withdrawn; it is not raw-source
evidence and must not be reused as a literal-zero-price claim.

## Remaining requirement and authority

The full A/D five-symbol financial comparison still needs accepted original
funding settlement inputs, May BBO and causal NEWS/MACRO, the continuous
financial account pipeline and fixed four-arm replay. Whole-calendar funding
rates alone do not satisfy settlement accounting. No performance result,
blind-campaign credit, new model execution or trading authority follows.
All readiness flags remain false and policy is `REJECT_ALL`.
