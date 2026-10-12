# Notifications and EVEDEX handoff - 2026-10-12

## Verified result and remaining gate

One marked `[KAIROS QUALIFICATION TEST]` was accepted by Telegram in the
owner-corrected test group at 09:05:52 UTC. The response identified the exact
approved group and message 2. This proves transport acceptance, not that a
person saw it, an operational alert loop, or production notification readiness.
Owner visibility and the group's role for ongoing technical alerts are pending.

The current credential was imported by a reviewed local program from the
owner's file into the dedicated private notification contour. It differs from
the historical exposed credential and resolves to the expected bot. Neither
credential values nor response titles/bodies were printed or committed.
Previous tokens and all old/unknown journals remain unchanged.

The original test ID was refused with `CHAT_NOT_FOUND` after one `getMe` and
one `getChat`, with zero sends. The owner then supplied the corrected ID. Its
separate, recipient-scoped attempt made one `getMe`, one `getChat`, and one
`sendMessage`. A durable, protected reservation preceded that sole send;
automatic retry is prohibited even if a terminal outcome is missing.

## Windows protection and evidence identity

The initial generated reserve failed the strict Windows ACL check before any
HTTP call: its ACL included a logon/session SID. Only the two newly generated
handoff/reserve files' ACL metadata was corrected; both content hashes stayed
unchanged. A subsequent local validation refused the legacy token file's
missing final newline before creating a continuation guard or making HTTP
calls. The reader now accepts an exact single token with an optional LF/CRLF
terminator and still rejects additional whitespace/lines.

PowerShell-based ACL application passed locally but repeatedly timed out on
the hosted Windows fixture. The underlying shell hang was not proven.
The accepted implementation instead uses native Windows token/DACL APIs,
rejects UNC/remote/reparse/nonregular targets, and independently verifies the
protected three-ACE allowlist: current user, SYSTEM, Administrators. There is
no session-SID exception, external module loading, or helper process.

| Evidence | Revision or SHA-256 |
| --- | --- |
| Pinned Deploy source, unchanged | `0427f7cf1e1cd70f2ddd05b80b4d7d6219736412` |
| Native ACL helper source | `f7b2f249c028a4a947b7279e677f21ee85bee8fc` |
| Actual corrected-test controller source | `3432ee81f930887785a5ac5ecd2c4f3cb9bb6c5b` |
| Original-ID read-only result | `d97b016332038598b46cc1b414b9610ff28ee45b1df1bc8ab76577482f80bd86` |
| Corrected-test transport result | `59d102c129f0baf17f548763be1f55587be32673a3be7bfe81b57bb5966d489a` |
| Actual corrected controller bytes | `eda1ad2f83b1da8e10a0427355a7083f051741220f8b8e9eb5be8279568e0f68` |

Both exact-source Windows validation and CodeQL passed for the actual
[corrected-test source](https://github.com/Kairos-cryptoAI/kairos/actions/runs/38227675364).
The separate status-alert planner adds 13 offline contracts; the combined
Windows Python 3.11/3.14 suites pass 54 tests. This is not a venue/live gate.

## Status-file-only operational planner

[The planner](../development/ops_alerts/runtime_status_alerts.py) binds the
existing R4 status path and owner. It calls only Persistence's pure, bounded
status-file observer, not its database/Redis exporter. No business Compose
services, consumer, database connection or polling daemon was started.

It reserves an event durably before its injected sender, preserves guards,
deduplicates unchanged incidents and across restart, fails closed on malformed
journals or unknown sends, and permits recovery only after an accepted firing
and an actual fresh healthy observation. New journal/guard files support strict
private-ACL callbacks. It remains **plan-only/unarmed**; the recipient binding,
actual firing/resolved delivery, long-running loop and restart qualification
must not be inferred from fake-sender tests. It is not a Prometheus/Alertmanager
end-to-end proof or an exactly-once delivery claim.

## New runtime failure, separate from historical acceptance

The accepted R4 restore/backup receipts remain valid historical evidence.
The R4 serve subsequently failed closed at 07:57:50 UTC with a sanitized
`TimeoutError` in the Redis stream-read path and exited 1 (no OOM, no restart).
Its current status SHA-256 is
`ebb10dfa1050aea1fd95b473e0834a520959fcbeba8461a2183f90fce96a0593`.
The native pure file observer independently reports `failed_closed`, stale.
The actual pinned Core wheel has a 5-second blocking read and 15-second socket
timeout; the cause is not established or declared fixed. No restart, database
mutation, lease reset, queue reconciliation or legacy connection was performed
in this notification task. The earlier running observations are historical.

## EVEDEX stage has not been started

The requested order remains notifications, then EVEDEX qualification.
Venue HTTP/auth/signing/order calls in this task are all zero.

Source preparation confirms the fixed DEV trading/auth/WebSocket `.tech`
origins and chain 16182 against the
[official SDK configuration](https://raw.githubusercontent.com/evedex-official/exchange-bot-sdk/master/src/params.ts).
Kairos's locked SDK 1.2.11 transitive network metadata still contains the old
421614 DEV chain; the existing fixed override to 16182 is intentional and
preserved. Current upstream is a moving reference, not proof of npm artifact
contents or current five-symbol liquidity.

After notification recipient/visibility acceptance, the next stage is an
isolated GET-only DEV preflight, including all five exact DEV instruments.
The existing one-shot public qualifier does not prove authenticated account
pairing, five-second/2-second freshness limits, 24-hour availability or TCA.
Full qualification still needs accepted 24-hour five-symbol evidence, then
separately armed DEV canary and seven-day soak. No order/canary is authorized
by this handoff, and no main-wallet signing credential may be used implicitly.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`. UI/UX, trading and paid model
calls remain OFF. See the [signed scoped receipt](receipts/notifications-evedex-20261012.json).
