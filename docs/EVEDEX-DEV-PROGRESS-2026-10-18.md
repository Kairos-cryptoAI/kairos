# EVEDEX DEV: signed public snapshot — 2026-10-18

One existing public-preflight run completed at **20:27:41 MSK**
(`2026-10-18T17:27:41.761707Z`). Exactly 12 anonymous GET requests reached
`https://trading-api.evedex.tech`; all returned HTTP 200, with no transport/JSON
error or automatic retry. The earlier same-day attempt stopped before the
network while Deploy was dirty; it sent zero requests. No live matching
preflight was present when this run was admitted.

The sampler implementation SHA-256 remained
`1c25df0809358f6f9c371cbd8c08851c618abeab85f573b6f09ccf81db1b8380`.
The source/clean-main checks admitted Deploy
`94d0c2faee01d9c5ff2173c882651eeb2634610a`. No sampler, evaluator or threshold
was changed to obtain this result.

| Required DEV instrument | Book observation | Recent trades |
| --- | --- | --- |
| BTCUSD:DEV | Two-sided, 0.94 s old, 0.0123 bps spread | 36; latest 2.43 s old |
| ETHUSD:DEV | Two-sided, 0.94 s old, 2.0231 bps spread | 36; latest 2.59 s old |
| SOLUSD:DEV | Empty | 36; latest about 151992 s old |
| BNBUSD:DEV | Empty; `instrument_not_fully_enabled` | None |
| XRPUSD:DEV | Empty | 6; latest about 357527 s old |

The market snapshot was active. The five-instrument result remains **BLOCKED**;
HTTP success and fresh BTC/ETH books do not supply the other three books.
These serial one-shot measurements are not simultaneous basis measurements,
fill/slippage proof, accepted clock-skew evidence, a 24-hour percentile or a
seven-day soak. All five instruments remain mandatory and in the denominator.

Private raw replies, request accounting and report are retained at
`D:/Kairos/runtime/evedex-dev-preflight-20261012/sample-20261018T172723Z-df58d2c0-9ba9-4923-88fa-f62ff4a5fa56`.
`report.json` SHA-256:
`ceba619f8a1d209804d9a2878bfcc98d5cb8dd06b2bf851f5cd41d20bcff91d5`.
Its detached GPG signature was verified against
`40AF365C6682B73D056A6A274DBFF6B65BE9F827`.
Earlier runs and failures were retained, not overwritten.

No authenticated/account request, exchange signature, owner-key read, faucet,
order, transfer, trading service or paid model request was used. No 24-hour
observer, canary or soak was started around the blocked prerequisite. Demo
evidence is not substituted for DEV qualification. There was no new support
message or presumed account/signing acceptance.

The existing finite engineering work and remaining gates are documented in
[the October 16 receipt](EVEDEX-DEV-PROGRESS-2026-10-16.md). The separate runtime
recovery is tracked in [its own receipt](RECOVERY-2026-10-18.md).
Strategy work remains deferred. `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain unchanged.
