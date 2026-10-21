# EVEDEX PROD signing clarification — 2026-10-21

One technical inquiry was sent to `support@evedex.com`, the address published
by the official EVEDEX Help Center. The connected Gmail account returned
message/thread ID `1a15e996edffa6fa` with label `SENT`; a subsequent read of
that exact message confirmed recipient and subject. This records dispatch,
not delivery to an engineer or an answer. No second message was sent.

Subject: **Kairos integration: PROD EIP-712 chain ID and non-mutating signature validation**.

The inquiry asks EVEDEX to resolve the published SDK / current master / deployed
frontend chain-ID discrepancy, identify the supported production SDK version
and complete signing domain, and provide an authoritative non-mutating
signature-validation procedure. It also asks whether the delegate-list API alone
proves active signing authorization.

Only public version, chain and source-link information was included. No keys,
wallet address, account ID, balance, private receipt or attachment was sent.
The letter states that no order or transfer was submitted for this investigation.

Pending an authoritative answer, the local encrypted signer remains a candidate,
not accepted production custody/signing authority. No guessed chain ID is
promoted into a production binding. This support inquiry does not enable LIVE,
change the strategy, or supersede readiness/risk/owner-arm gates.

Public references:

- [Official support contact](https://help.evedex.com/ru/articles/11142835-почему-я-не-могу-войти-в-свой-аккаунт-evedex-распространённые-проблемы-и-решения).
- [Official SDK source](https://github.com/evedex-official/exchange-bot-sdk/blob/master/src/params.ts).
- [Exchange OpenAPI](https://exchange-api.evedex.com/api/openapi.json).
- [Prior engineering evidence and remaining limits](ENGINEERING-2026-10-21.md).
