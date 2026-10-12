# Technical notification acceptance and DEV preflight

## Result

The owner confirmed seeing qualification message 2 and selected the corrected
temporary group for all notification classes. The exact
[direction](../development/ops_alerts/notification-routing-20261012.json) and
a separate private operator attestation record that reply. Neither rewrites
the original transport receipt nor claims Telegram-authenticated user identity.
The eventual final group was not redirected or inferred.

One real R4 firing was accepted as Telegram message 3 at 14:13:53 UTC.
Repeated manual processes and actual Limited scheduled dispatches retained
the same journal hash and sent no duplicate for the unchanged incident.
The hidden `Kairos-R4-TechnicalAlerts-20261012` task polls the fixed R4 status
file every two minutes and at owner logon, with `IgnoreNew` and no automatic
retry of unknown sends. Only technical R4 alerts are enabled; strategy, risk
and trading sources remain dormant. This is not Prometheus/Alertmanager
end-to-end or exactly-once delivery proof. No actual recovery delivery or
human visibility of the operational firing is claimed.

The initial scheduled action exited 103. A separate Limited-context probe
found the old venv's Roaming base absent, the physical Python 3.11.15 present,
and the old launcher exiting 103. The corrected task uses a new private
notification-only environment with that physical base and unchanged locked
Persistence dependencies; the Persistence venv was not changed. Native
corrected dispatches returned 0. Monitoring depends on this PC and the
owner's logged-on session: it is not off-host or production availability.

## EVEDEX public sample, not venue qualification

One sample from 14:38:45 to 14:39:14 UTC made exactly 12 reserved public GETs;
all returned HTTP 200. The required DEV snapshot was:

| Instrument | Two-sided book | Recent-trade review | Other condition |
| --- | --- | --- | --- |
| BTC | Fresh; 0.073 bps single-snapshot spread | 36 valid recent rows | Visible |
| ETH | Fresh; 2.065 bps single-snapshot spread | 36 valid recent rows | Visible |
| SOL | Both sides empty | One stale row | Visible |
| BNB | Both sides empty | No rows | `visibility=none` |
| XRP | Both sides empty | No rows | Visible |

All five instruments are mandatory. Empty books and hidden BNB block the
next gate, so no 24-hour campaign, authentication, wallet signature, order,
DEV canary or seven-day soak was started. No signing credential was read.
A key does not resolve the observed public-liquidity limitation. The asset
universe and environment were not reduced or switched automatically.
One snapshot establishes neither 99% availability, p95 costs, basis/slippage,
account pairing nor a complete 24-hour window.

The first local entry attempt refused before filesystem/network access due
to a callable signature mismatch; a native-entry regression now covers it.
The original collector also expected `id` for public recent trades. The
locked official `@evedex/exchange-api` 1.0.70 `RecentTrade` contract instead
requires `executionId`. That local checker was corrected; all 12 saved raw
response hashes and original capture timestamps were rechecked with zero
new HTTP requests. The original report remains unchanged, with the separate
schema review explicitly distinguishing the local error from venue data.

## Evidence and remaining boundary

The [signed scoped receipt](receipts/notifications-evedex-20261012-operational.json)
records exact code/evidence hashes and native task outcomes. Windows Python
3.11/3.14 each pass 85 ops tests; Ruff, static documentation/manifest checks,
and exact-source Windows validation/CodeQL pass. The earlier interpreter/
byte-policy source's four-platform adaptive fixture workflow also passed.
Synthetic recovery tests are not a real resolved notification.

The R4 serve still reports its separate failed-closed Redis timeout. This
work did not restart it, contact/mutate the old database/queue, resume frozen
research, alter Deploy's boot binding, spend paid API budget, or accept the
unrelated adaptive WIP as a clean release. UI/UX remains deferred.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`.
