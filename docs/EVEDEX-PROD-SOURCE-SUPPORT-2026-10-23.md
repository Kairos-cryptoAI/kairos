# EVEDEX PROD reconciliation-source inquiry — 2026-10-23

One user-authorized technical follow-up was sent to `support@evedex.com` in the
existing [PROD signing inquiry](EVEDEX-PROD-SUPPORT-2026-10-21.md). The official
[Help Center contact](https://help.evedex.com/ru/articles/11142835-почему-я-не-могу-войти-в-свой-аккаунт-evedex-распространённые-проблемы-и-решения)
was checked again. No second recipient, CC, attachment or resend was used.

Gmail returned message ID `1a16a02e428daa61`, thread `1a15e996edffa6fa`, label
`SENT`. An independent metadata read confirmed that exact message, recipient,
reply context and subject. Its recorded send time is **21:25:36 Moscow** on
23 October 2026. The first post-send read hit a shared Gmail quota error; only
the read was retried, never the send.

Subject: **Re: Kairos integration: PROD EIP-712 chain ID and non-mutating
signature validation**.

The inquiry asks for official endpoints/schema and documented guarantees for:

1. Coherent account state: a snapshot/revision, replay watermark or supported
   reconciliation protocol across positions/orders/protections/balances.
2. Complete fills/fees after disconnect, stable IDs, bounded intervals/cursors,
   history membership, retention and late-arrival behaviour.
3. The funding-payment and settlement ledger, exact amounts/sign/currency,
   unique IDs, finality, corrections and late charges, distinct from balances.
4. Original entry/position lineage of TP/SL, including partial fills and
   cancellation/replacement; the meaning of `triggerOrder`.
5. Exact decimal versus JSON-number precision and replay evidence semantics.
6. A non-mutating/read-only integration validation example or procedure.

The letter names only the public pinned SDK/API versions and official source
links. No key, wallet address, account ID, balance, private log or receipt was
sent. It states that order submission remains disabled; it makes no commitment
to trade, deposit or move funds.

`SENT` proves Gmail dispatch, not recipient delivery, engineering acceptance
or an authoritative answer. No EVEDEX answer is credited by this receipt and
no local verifier, custody identity, readiness flag or owner arm is promoted.
The [source/accounting evidence](PRODUCTION-SOURCES-ACCOUNTING-2026-10-23.md)
remains the engineering baseline while independent LIVE Risk is implemented.
