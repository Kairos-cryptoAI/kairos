# New Telegram test delivery — 2026-10-18

## Accepted finite result

At **22:43:42 MSK** (`2026-10-18T19:43:42.461092Z`) Telegram API accepted
one new protected test message, **message ID 89**, in the approved group
`-1004475802889`. Its label is `[KAIROS DELIVERY TEST 2026-10-18 #1]`.
The returned text matched the exact new test body. `getMe` verified the expected
bot and `getChat` verified the exact group before the single send.

The owner subsequently answered **"Да, сообщение видно"** in this chat.
This is a direct owner visibility observation recorded separately from the
API receipt, not authenticated Telegram-user identity or an alteration of
the original send result. The new test is accepted for transport and owner
visibility; it is not a replay of the missing October 16 runtime alert.

| Method | Attempt count |
| --- | ---: |
| `getMe` | 1 |
| `getChat` | 1 |
| `sendMessage` | 1 |

No automatic retry occurred. The existing create-only qualification primitive
reserved the attempt before HTTP; its retained guard prohibits replay.
The source/transport admission uses the current R7 SQL protected route and
reviewed token handoff. The R6-named qualifier is reused only as an already
tested send-once primitive, with an adapter for the explicit new test body;
no legacy runtime, journal or source identity was adopted.

## Bound evidence

- Meta source: signed `41ab334fec1f0318e8b8ebf000eb87a6227b4ba5`.
- Deploy source: signed `12dbe9fd9d596bd47718d5e606bfa939baabf15f`.
- Current R7 route binding SHA-256:
  `e95c2c707a60f250a84df63ff2078eef11bd73bfdd9a061e3375d36050f3fc85`.
- New event:
  `2a6de7e2e4c37a48e1b73cb904c06034b9626492e8c3f591d77b7a2ad5719101`.
- New text SHA-256:
  `dc1f2b52f94b020b948178c73a9c87a3b3ec1fbdce8f734804d53a39bc1b90f8`.
- Private evidence root:
  `D:/Kairos/runtime/telegram-delivery-test-20261018`.
- `test-receipt.json` SHA-256:
  `c68379179ca8ac854402787bd56104ec121dc8e5f796a11ba5d04cf0b59f5673`.
- `human-ack.json` is a separate local owner-observation record bound to that
  exact receipt/message/event. It does not rewrite the earlier
  `human_visibility=NOT_YET_CONFIRMED` send-time snapshot.
- Owner-observation SHA-256:
  `2e09629e909384d8470933b6af354c6b8e70984da8fb9f2a858fb74d59f341a5`.
  The test summary, API receipt and owner observation have trusted detached
  GPG signatures retained next to their private originals.

The reviewed private driver was GPG-signed before execution. Three offline
adapter tests passed on Python 3.11 and 3.14: fixed destination/new text and one-send ceiling,
rejected destination/method, and no replay after timeout. The existing
qualifier's eleven offline tests also passed. Credential values, full API
replies and raw transport errors were not printed or committed.

## Scope limits

No operational alert journal was reset or used to manufacture a failure.
The old unknown-outcome send/guard remain retained; no old message was resent.
No scheduled task, database, queue, trading service, venue account, provider
budget or readiness flag was changed by the test.

One delivered message does not prove full Prometheus/Alertmanager integration,
host-loss detection, production escalation, extended reliability or a tested
real trading incident. Those operational deployment checks remain in
[the non-strategy launch register](LAUNCH-REMAINING-2026-10-18.md).
