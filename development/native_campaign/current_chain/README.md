# CURRENT whole-system verification (opt-in)

This target composes the existing current Catalyst, Text, Macro, Router, review,
Risk and native SIM components. It is not the old cached twelve-candidate
reconstruction, an alpha claim, a production driver, or a blind campaign.
Historical/frozen dependency locks, research ledgers and evaluator code are not
rewritten by this target. The new lock explicitly pins current signed sources.

Default, with the installed noneditable environment:

```powershell
python -I -m kairos_native_campaign.current_verify
```

An explicitly authorized finite run uses `--execute`. The host bootstrap is
intentionally Windows/local-specific. It reads the previously authorized
existing OpenAI project credential in memory, not a new key/project or a copied
secret. All requests use the existing cumulative PostgreSQL campaign authority
(`kairos-dev-qualification-v1`, OpenAI cap $12), with an additional hard pre-call
envelope of $1 and 24 attempts, no retries and conservative unknown holds.
Registered prices are cost-accounting inputs, not a verified provider invoice.

The real-source check always requires fresh news (`--require-fresh-news` is
retained as an explicit compatible spelling).
This refuses an empty/stale news snapshot before any paid stage. Never rerun
paid Macro repeatedly merely because an otherwise valid no-signal cut did not
exercise downstream stages. There is no automatic paid polling/retry here.

Traversal completion and acceptance are separate. `verification-acceptance.json`
checks committed real provider responses, actual fresh news, Catalyst plans,
native review, persisted Risk and SIM execution receipts. A completed quiet cut
is `PARTIAL_REQUIRED_STAGES_NOT_EXERCISED`, with exit code 2; it is not a full
path pass. Full trade-close evidence is reported separately. Fixtures have no
credit toward either real-source acceptance or profitability.

The replaced initial-only driver was execution-incompatible: its sealed short
prefix could not include full 54h provenance or later executable books. Its
receipts and the diagnostic `initial_execution_compatibility` remain unchanged.
The current default records one new original continuous V2 tape under a fresh
identity declared before the first frame (at most 900 seconds, 60,000 frames and
128 MiB raw payload). It does not stitch or re-root existing segment tapes.

Actual source capture, Catalyst decisions and real model responses happen first.
An observed request is a create-only journal entry, **not** a Risk approval or
order. Once capture ends, the full historical/observed bar chain and original
native frames are imported, then sealed and verified. Only then is a native
SIM session created and the observed requests replayed. Replay preserves their
original timestamps, selected-frame watermarks, expiries and account ceilings;
actual replay wall clocks are recorded separately. It is explicitly later
offline native SIM, not actual live Risk/execution. Missing future observations
are reported as incomplete; positions are never artificially closed.

Run `--execute --capture-only` for the zero-provider real-source tape preflight.
It imports/verifies a real complete tape but earns no model or trade coverage.
Its history cutoff is the next complete minute, not a strategy decision cut.
For a model run, the existing configured feed can be chosen explicitly with
`--text-feed https://cointelegraph.com/rss` (default is CoinDesk). There is no
automatic feed fallback, altered publication date or relaxed 30-minute TTL.
Paid calls additionally require the original remaining source horizon, healthy
book/market streams and fresh news. A later cut never renews the original
capture window. Both reviews still must fit the original two-second quote
deadline; slow real responses cause refusal, not refreshed timestamps.

The bootstrap creates only a uniquely named isolated `kairos_sim_current_*`
database/container. It never migrates an existing database or changes legacy
queues/consumers. The owned SIM container is stopped and retained afterwards;
only the owned credential-free loopback budget tunnel is removed. Existing
runtime containers are not modified.

## Evidence boundaries

- Public source bodies, publication/event, receipt and persistence clocks are
  retained. News coverage means the exact captured RSS item roster, not all
  world news or interval completeness. Old news is not made fresh.
- Quant uses real funding/OI, a complete retained 13-point OI window and a
  separately declared observed force-order window. Missing values are not zero.
- Macro is the actual existing model-driven allocation. Without an admitted
  numeric macro-release/on-chain source those values explicitly remain
  unavailable; technical indicators are not relabeled as inflation or rates.
  The existing fixed official-context capture also supplies actual Federal
  Reserve monetary-publication summaries and BLS CPI records if available.
  Original publication dates, partial/403 failures and exact source hashes are
  retained; a summary is not relabeled as the full statement or a rates print.
- REST BBO is never promoted into continuous book evidence. Only separately
  recorded V2 WebSocket frames can be considered by native SIM.
- All four Catalyst arm/denominator dispositions remain visible. Only the
  `combined` arm may create a durable SIM admission in this one integration run.
  This is not a completed four-account economic matched-A/B campaign.
- The new exact-clock observed-SIM V2 intent keeps the existing V1 default,
  bytes and restrictions intact. Independent contract and PAPER Risk guards
  categorically prohibit V2 PAPER/LIVE approval.
- Hypothesis preview and final candidate have different identities and distinct
  reviews. Actual provider latency never renews the original two-second quote,
  hypothesis validity or protection. Stale evidence or a veto is a real refusal.
- An expired original intent remains expired even with a newer native book.
  Slow reviews may therefore yield no executable trade; that is not a pass.
- New public stream artifacts may use a fresh C: output parent to avoid D:
  flush latency. No prior artifact is moved. A bounded ordered recorder worker
  separates socket delivery from native validation while retaining every body
  and its actual delivery clock. The existing recorder, native source policy,
  persistence clocks and five-second gates remain unchanged.
- The bootstrap declares one at-most-fifteen-minute original native-book stream
  and a seventy-second initial Quant window. Every retained TEXT delivery must
  match one admitted original frame and its exact payload bytes. Overflow,
  source silence, reconnect, clock regression or missing suffix is fail-closed.
  The previous short-segment selection helper remains only for old callers and
  receipts; the new bootstrap never uses it to manufacture continuity.
- A positive PostgreSQL/controller fixture is labeled synthetic input/model
  mechanics, separate from actual source/model evidence and from profitability.
- There are no EVEDEX requests/orders, DeepSeek/X calls, PAPER/LIVE services,
  real-money orders or readiness promotions in this target.

## Checks

The default test suite uses no external provider/database. The durable positive
test skips unless the caller explicitly supplies
`KAIROS_CURRENT_SIM_DATABASE_URL` for a freshly owned, empty, UUID4-named,
loopback-only SIM database. It verifies the schema without migrating it and
preserves the resulting artifacts. Never aim it at any old runtime/SIM database.
