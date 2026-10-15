# Native campaign engineering composition

This is a separate, opt-in **OFFLINE_ENGINEERING_FIXTURE**, not a strategy
selection, paid model qualification, shadow enrollment, trading runner or
economic A/B campaign. There is no CLI tick, default database, dotenv, live
provider fallback, exchange/SDK, execution service or order capability.

It connects the actual pinned causal campaign scheduler, Strategy evaluator,
Router projector, CandidateReviewBrain, LLMGateway, shared PostgreSQL usage
budget, SimulationRiskPolicy and Persistence journals. Only the finite
`NoNetworkResponsesTransport` is accepted. Test OHLC, NEWS/MACRO messages,
Responses-shaped outputs, token usage and hypothetical equity are synthetic.
They prove component composition and durability, not model quality or alpha.

The three preregistered arms share one captured bundle and one original strategy
evaluation. A quiet strategy does not trigger review, but still permits the
separate research proposal observation. A proposal is never supplied to Risk.
Only the strategy-review lane produces a durable **SIM-only diagnostic** Risk
decision; no admission or simulator execution command is created here.
The existing SIM repository atomically queues its tape/session/Risk diagnostic
artifacts in this disposable database. They remain unpublished; no consumer,
publisher or legacy/runtime queue is accessed.

The new source-bound scheduler identity includes component code, schemas,
context renderer, static prompt artifact, no-network transport and exact SIM
session/sizing policy. Old plans, evaluators, receipts and unfinished adaptive
development files are not rewritten or adopted. Its independent `uv.lock` pins
current accepted Git dependencies rather than changing historical replay locks.

Important distinctions are retained:

- The original closed-bar anchor, campaign source cutoff, actual routing/context
  clock, observed provider response and PostgreSQL write clock are different.
  No new route or source is backdated to an earlier market event.
- The static prompt-artifact hash and the actual compiled request hash are
  separate. Both are retained, alongside the exact response/model/request and
  durable reservation/START identity. The native provider output schema differs
  from the explicitly normalized research receipt schema; the mapping is frozen.
- Historical debt, reservations and committed costs live in the same adopted
  PostgreSQL provider ledger. No implicit zero-spend adoption or monthly reset
  occurs. Fixture adoption is allowed only during explicit test preparation.
- Saved native review/Risk bytes can complete interrupted persistence after a
  reconnect without new provider, budget or evaluator work. A START without a
  saved response remains UNKNOWN and is never resent. Missing/late/failed arms
  stay in the full denominator.
- Replay re-resolves the registered sealed window and verifies the entire bar
  and global book chains before saving a diagnostic decision. Corrupting an
  unrelated XRP book blocks a saved BTC review even when its bar page is intact.
- Stop-based sizing preserves 0.25% per-trade and 1% aggregate ceilings for its
  explicit hypothetical snapshot. It is **not** a real account/portfolio-risk
  reservation or a venue sizing qualification.

## Reproducible gates

```text
uv sync --locked --no-editable --dev
uv run --locked --no-editable --dev python -I native_gate.py check-source
uv run --locked --no-editable --dev python -I -m pytest --import-mode=importlib -q tests/test_pure_contracts.py
```

A native PostgreSQL proof additionally needs an externally created, empty,
local PostgreSQL 16 target named `kairos_sim_test_campaign_<UUID4 hex>` and an
explicit `KAIROS_NATIVE_CAMPAIGN_TEST_DATABASE_URL`. `native_gate.py prepare`
rejects an occupied/remote/non-disposable target before DDL and installs only
the existing RESEARCH_CAMPAIGN migration profile. Neither test nor scheduler
creates or migrates an application database.

```text
uv run --locked --no-editable --dev python -I native_gate.py prepare
uv run --locked --no-editable --dev python -I -m pytest --import-mode=importlib -q tests/test_native.py --junitxml=native-campaign.xml
uv run --locked --no-editable --dev python -I native_gate.py check-result native-campaign.xml
```

The result guard requires the exact one native test to PASS, not skip. `-I` and
importlib test loading prevent working-tree modules from impersonating the
installed non-editable wheel. Each platform native proof uses a new target.

Primary/legacy databases, Redis, consumers, outbox recovery, paid APIs, EVEDEX,
PAPER and LIVE are outside this profile. `PAPER_QUALIFIED=false`,
`ALPHA_READY=false`, `LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL` remain.

The native target deliberately leaves its disposable fixture corrupted after
the final negative integrity scenario; it never repairs or reuses that target.
Interrupted writes plus connection close/reopen prove durable replay, not a
process kill, host/power failure, backup restoration or production rollout.

## Separate opt-in public capture tool

`tools/capture_sim_tape.py` defaults to `--plan`; the existing offline/native
campaign fixture and its source lock stay unchanged and cannot launch it.
Explicit execution uses an independently prepared, exact non-editable
Quant/Persistence/Core environment and a fresh UUID4 PostgreSQL 16 simulator
database. It captures at most 300 seconds and 16 MiB of accounted market inputs,
stops producers before the final durable drain, and seals only fresh five-symbol
bar/book coverage. CLI credentials are read from a protected file or a named
environment variable, never a command-line DSN. It calls no models or venue orders.

The pinned V1 recorder retains normalized book levels, original clocks and raw
payload hashes, not raw WebSocket text. A successful capture is not V2 raw-source
attestation, complete analytics, fill economics, venue qualification or alpha.
The separate hermetic adapter tests run in CI without a public connection.
