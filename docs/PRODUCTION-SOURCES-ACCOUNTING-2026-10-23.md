# PROD transport, source truth and capital accounting — 2026-10-23

This continues [the managed lifecycle](PRODUCTION-LIFECYCLE-2026-10-23.md).
It records engineering changes, not completed real EVEDEX execution or a LIVE
admission. All readiness flags remain false; `STRATEGY_POLICY=REJECT_ALL`.
No real exchange request, order, signing credential, transfer or paid model
call was used during this continuation. Existing non-trading services,
primary/legacy databases, queues, strategy and frozen campaigns were untouched.

## Implemented

- An additive PROD-only transport uses the installed pinned EVEDEX SDK
  1.2.11 / exchange-api 1.0.70 / exchange-crypto 1.1.0. Explicit API-key preflight
  binds the exact exchangeId; custody and the actual sender must agree on
  account, reviewed schema and the SDK's chain 42161. The earlier synthetic
  161803 binding is rejected, never silently rewritten.
- The five pre-signed POST operations preserve decimal REST bodies and use
  the corresponding SDK method, behind the existing one-use durable signing
  and dispatch claims. No wallet login, new signer, generic URL, transfer,
  withdrawal or mutation retry is introduced. Cancellation requires a positive
  read of the exact cancelled order/protection; an ACK or missing record is
  not cancellation evidence.
- The actual SDK RestClient is bounded to fixed HTTPS origins/routes/methods,
  with no redirects, environment proxy, JWT refresh or hidden API-key 401 retry.
  HTTP timeout is 20 seconds and response bound 4 MiB. IPC allows a fixed 4 KiB
  envelope; oversize/unknown mutations latch rather than retry. Public errors
  cannot include SDK headers or credential-bearing diagnostics.
- The same typed transport collects bounded account identity, order history,
  TP/SL history and funding-balance replies. It checks account, counts,
  duplicate IDs/cursors, time/size/page bounds and retains query/response hashes
  and retrieval times. These are canonical **parsed SDK JSON**, not original
  HTTP bytes or an authoritative cross-page account snapshot.
- Fresh opt-in state-v3 / receipt-v2 / accounting-v1 composition releases an
  exact reservation only after an independently accepted complete terminal
  receipt and a separate accounting append. The original reservation and
  receipt are immutable and retained. Default state-v2/receipt-v1 behaviour
  remains unchanged; no retained database is migrated.
- Accounting checks the full canonical payload and every SQL projection,
  database/context/account/arm/request/effect/trade lineage, actual full closes,
  fees, complete signed funding and zero residual/unowned exposure. It shares
  the admission account lock; foreign keys and isolated roles prevent a runtime
  writer from inventing a release. Profit never cancels the adverse loss floor.
- `reconcile_closed_account(..., accounting=...)` composes the exact terminal
  receipt with that acceptor. A failed accounting append retains the receipt.
  Original acceptance time is database-stamped, so an accounting outage does
  not permanently strand a reservation after the two-minute source window.
  Exact replay preserves the original UUID/hash; changed proof cannot replace
  it. First-time stale evidence still fails and cannot be backdated.

## Important remaining source and Risk boundary

The real EVEDEX history **is not connected as authoritative exposure or
settlement evidence**. The fixed verifier refuses that promotion. Installed
primary declarations do not establish an account-wide shared revision,
immutable paginated history membership, a complete funding-payment ledger,
the original TP/SL entry parent or recoverable complete fill publication
positions. `getFunding` returns coin balances, not all funding payments.
JavaScript Number parsing is also not exact original numeric wire evidence.
Repeated GET equality or a local sequence cannot manufacture these guarantees.

Primary references: [official REST gateway](https://github.com/evedex-official/exchange-api/blob/master/src/exchangeRestGateway.ts)
and [official API types](https://github.com/evedex-official/exchange-api/blob/master/src/utils/types.ts).
Mutable master explains the contract only; the exact installed package hashes
below identify what was reviewed. No speculative SDK upgrade was made.

The shipped Risk service is still PAPER/DEV-only: its config rejects LIVE,
PaperRiskPipeline builds PAPER decisions and its account inputs are PAPER
recovery records. A Core LIVE DTO or an `approved=True` bridge is not an
independently authenticated LIVE producer. No PAPER approval was relabelled.

Consequently, this is **not a completed real-money PROD path**. Completion needs
an accepted venue source contract providing coherent account state and complete
fees/funding/settlement/protection lineage, then a current authenticated LIVE
Risk producer using those facts and the accepted custody/owner deployment.
The additional key alone cannot close this gap. Old DEMO book-quality gates,
off-host infrastructure purchases and new strategy directions were not added
as requirements by this work.

## Accounting semantics and proof limits

Net economics are `gross PnL - fees - signed funding cost`, where positive
funding is a debit. Admission retains the conservative cumulative charge
`max(0,-gross) + fees + max(0,funding debit)`. Historical cap/equity/loss floors
survive new arms and contexts; there is no inferred UTC-day reset or profit
offset. This may conservatively double-count an authoritative reported loss;
an ordinary daily reset requires a qualified account ledger, not a timer.

The native fixtures use real PostgreSQL roles, locks, constraints and journals
but explicitly synthetic venue/authority inputs. SDK transport tests use the
real pinned SDK classes with offline HTTP adapters. These tests prove software
boundaries, **not actual exchange acceptance, account continuity, strategy
profitability or real fills**.

Local Ruff, format, mypy (55 source files), Bandit and wheel/sdist build passed.
The complete unit run reported 935 passed, eight passing subtests, one skipped
and 51 deselected integration tests (944 JUnit cases including skip/subtests).
The sidecar suite passed 38 tests, including existing DEV regressions.
Final [Execution CI 40000553523](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/40000553523)
passed Linux Python 3.11/3.14, Windows Python 3.11, all exchange adapters,
pinned SDK tests/signature parity and native TimescaleDB integration. The
preceding failed CI remains visible; only its POSIX test-fixture defect was
corrected, without relaxing executable validation or skipping the test.

The fresh native default fixture passed concurrent release/replay, concurrent
new reservations and retained loss-floor checks. A separate native fixture
retained the original receipt through a real **122-second** accounting outage:
exact original UUID/hash replay and first accounting acceptance passed after
the source's two-minute lifetime. Concurrent replay released only once. The
original operator lease remained expired and new admission was refused both
before and after accounting; no authority was renewed to make the test pass.
Native default and delayed tests passed separately (3.69 and 124.70 seconds).

The earlier delayed probe proved the release assertions but then hit the
intentionally expired operator lease in an unrelated later reservation race.
That failed database `kairos_production_evidence_4edde78a0a9c` is retained. The
final probes use fresh databases `kairos_production_evidence_a2a2daa58c0a`
and `kairos_production_evidence_141d25244b91`, with separate isolated roles.
No fixture history, original lease or timestamp was rewritten. Earlier native
engineering/regression artifacts and failed fixtures are likewise retained.
Only the new explicitly owned fixture container
`kairos-prodpath-followup-20261023` was stopped after its ID/label check; its
databases remain recoverable. The existing non-trading successor and its
PostgreSQL/Redis containers, plus the existing shadow database, kept running.

## Signed source identity

Execution implementation commits are `09146eb1e216c1acf2d72ce7db49048d02cc557f`
and `9ef06e4b15ce5dc80153350cbd3bb140885831b7`; final source is signed
`d544ae9d9ac4eaa1670f02c7772899c42946756c`. The last correction makes the mocked
Node probe fixture executable on POSIX; production's executable check was not
weakened. Linux CI had exposed that Windows-only fixture assumption.

Deploy source is signed `6b42d732d2bbbf5a6633711bcb53030383b30608`.
Active current/full-path source projections, compose build identities and
dependency locks use that same Execution revision; historical locks are
unchanged. Current-chain locks are aligned without installing or resuming its
paused campaign. The meta repository uses `SELF` in the release manifest.

Implementation contract:
[production sources and accounting](https://github.com/Kairos-cryptoAI/kairos-execution-engine/blob/d544ae9d9ac4eaa1670f02c7772899c42946756c/docs/PRODUCTION-SOURCES-ACCOUNTING.md).

## Exact reviewed source artifacts

Paths below are relative to the installed `@evedex/exchange-api/dist/mjs`
directory, version 1.0.70:

| File | SHA-256 |
| --- | --- |
| `utils/types.d.ts` | `e0666fe249c8fb9cfa1ae445d8719d7b90ef50b889ab9e8254406def870e094c` |
| `exchangeRestGateway.d.ts` | `0b55f05c6fcba1627f544d65b44106db26621469397b88d3f23a6c7c21de6ec9` |
| `exchangeRestGateway.js` | `44f3aefb6359f6c19f97b46a1eec9df614dbc2de42d4e666b98875d23b60d5d8` |
| `exchangeWsGateway.js` | `13cf5b968be2a24f8f360ddd24ff01322ad97889d10e13dde605084387b2520e` |
| `utils/ws.d.ts` | `353d08aa1ac21cc2bbfed09e8ab9cfd3721d4ac6b57c9ad60e32f99353f72170` |

Local test artifacts are retained under
`D:/Kairos/runtime/prodpath-sources-accounting-20261023`:

| Artifact | SHA-256 |
| --- | --- |
| `unit-r3.xml` | `fefa7f586a2af7367e10f75cf218ba208d016ed7676805a31f5930006691c532` |
| `sidecar.xml` | `f07e70ae55fc2c1de28deb76c9ca536642b9d76ce185c8e43714916c7c590116` |
| `native-accounting-default-final.xml` | `640f31ff3a3b0b055f48e62b7ce15d474458c85ba61c58808a3ebf71db5c69b1` |
| `native-accounting-delayed122-final.xml` | `c3d755ac4074926e7c8e0e30e0e50e84b2128736eabb57c8c02441bbf49229dd` |
| `dist-r3/kairos_execution_engine-0.1.0-py3-none-any.whl` | `070c21a7127da8b60f8a89bd327b4dad2ae67ff866b5805020a695723b04f877` |
