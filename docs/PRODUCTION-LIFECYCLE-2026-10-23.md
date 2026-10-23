# PROD lifecycle engineering continuation — 2026-10-23

This extends, rather than rewrites, the earlier
[runtime/account checkpoint](RUNTIME-PRODUCTION-2026-10-23.md) and
[whole-project audit](PROJECT-CAPABILITY-AUDIT-2026-10-23.md).
It is not real-money acceptance. All readiness flags remain false and
`STRATEGY_POLICY=REJECT_ALL`; no owner arm, exchange order, transfer or paid
provider request was made by this work.

## Implemented path

The new opt-in `ProductionLifecycleEngine` reuses the existing protected EVEDEX
FSM and PostgreSQL trade/effect journals. Its public PAPER facade remains fixed
to DEV; default settings/factory still reject LIVE. The existing strategy,
research plans/evaluators, Trial 15, V2/V4/V5, old databases/queues and running
non-trading successor were not modified or adopted.

The path now connects original Core LIVE/PROD decision → immutable lifecycle/
signing association → independently persisted owner/operator/Risk/exposure
checks → reserve-before-sign → managed signing/wire claims → ACK validation →
partial fill → SL before TP → owned remainder cancellation → restart/recovery →
target/stop/timeout/emergency handling → flat account → independent terminal
evidence. Logical symbols, venue instruments, signing effects and lifecycle
effect IDs are explicitly mapped rather than treated as interchangeable.

`reconcile_closed_account` requires the exact durable FLAT trade, reconciled
account and a registered complete venue-history interpreter before appending
the terminal receipt. It does not promote an empty account GET to authority.

Concrete defects exposed and repaired during composition:

- Whole-position TP/SL `quantity=0` was rejected by the managed exit verifier.
  Only the TPSL branch now permits that documented convention; entry/direct
  close still require positive quantity and fresh owned exposure.
- Signed EIP-712 integer units were being used as REST units. The wire boundary
  now derives exact decimal strings and fixed IOC metadata, independently hashes
  that envelope, and refuses caller changes.
- The pinned SDK's TPSL signature excludes the REST parent field. A separately
  versioned managed schema profile keeps parent metadata required in the full
  request, independent Risk/exposure checks and immutable claims, without
  falsely asserting that the venue signature covers it. Old custody schema
  digests do not silently qualify; legacy/frozen schemas are not rewritten.
- Passive audit storage used a row-locking helper that required UPDATE rights.
  Native least-privilege testing refused it. The fix uses existing audit append
  and strict canonical identity checks under stable advisory transaction locks;
  UPDATE was not granted to runtime.
- Terminal receipt SQL field/parameter alignment and a row lock requiring
  mutation privilege were corrected before native acceptance. Reconciler roles
  retain append-only receipt and read-only reservation rights.

## Evidence and its limits

The finite native PostgreSQL lifecycle fixture passed with the real engine,
managed signer/dispatcher and cancellation verifier. It proved partial-fill
protection, remaining-entry cancellation, reconstruction/redelivery without
duplicate venue effects, target-versus-timeout resolution and a flat account.
Authority roots, signing backend/claims, SDK reader and venue in that fixture
are explicitly synthetic; this is not EVEDEX execution evidence.

A separate fresh native PostgreSQL database passed create-only association
concurrency, least-privilege/FK/immutability checks, real owner/operator/Risk
record and reservation insertion, and actual reconciler-role terminal receipt
insert, identical replay and conflicting-evidence refusal. Its venue/journal
proof inputs are explicitly synthetic DTO repositories, not real account truth.

Local native artifacts are retained under
`D:/Kairos/runtime/prodpath-engineering-20261023`. The first failed least-privilege
fixture and its database remain retained; repair was tested in a new create-only
database rather than resetting the old one. No primary or legacy database was
used. The fixture container is separately labelled and has public test-only
credentials; no user key file was read.

## What is still not a completed real-money launch

- No default PROD service or owner arm has been deployed. Actual qualified
  Risk/operator/exposure/history producers and matching transport/custody need
  to be composed and accepted on one current deployment.
- Real account/key/chain/schema identity and actual venue protection, partial
  fills, cancellation, reconnect and reconciliation semantics remain unaccepted.
  Earlier chain/custody uncertainty is not solved by a synthetic signature.
- Schema-v2 reservations remain fully counted after a terminal receipt. This
  intentionally does not silently enable capital reuse, reset daily loss or
  relax caps; a separately reviewed accounting reader remains necessary.
- The pending choice concerning a separate early owner-funded limited
  experiment versus the existing long research admission contract is unchanged.
  Exact dollar caps and a current signed owner arm are still required.

Implementation details and test entrypoints:
[Execution lifecycle contract](../../kairos-execution-engine/docs/PRODUCTION-LIFECYCLE.md).

## Reproducible source set and checks

- Execution: signed `cb07cfa0caf2d7cabc25f60ca63722ba7d9edac7`.
  [CI 39969723295](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/39969723295)
  passed Linux Python 3.11/3.14, Windows Python 3.11, exchange adapters,
  mandatory pinned SDK signature/wire parity and native PostgreSQL integration.
- Deploy: signed `37d5f3a13ed4082d1bfc02fd696d447498b44c3c`.
  Active current-release and full-path SIM projections and dependency locks
  reference that exact Execution commit; historical locks are unchanged.
  [Current release gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39970368337),
  [full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39970368234)
  and [Text/Macro/Router/Review/Risk composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/39970368400)
  passed. The first general CI attempt hit a 45-second Windows Docker Compose
  version-probe timeout; only its failed job was rerun, without changing the
  test or starting local PAPER services.
- The meta repository remains `SELF` in `config/current-release.json`; its
  signed commit records this report and the exact source set. Current-chain
  dependency locks now reference the same Execution revision, but its paused
  campaign was neither installed, resumed nor executed.

Local Ruff, format, mypy, Bandit and wheel/sdist build checks passed. The local
unit run reported 857 passed, eight passing subtests, one skipped and 50
deselected native tests. Its JUnit serialization counts 866 cases including
subtests and the skipped case. Separately, two native lifecycle/regression
tests and one fresh native store/terminal-evidence test passed. The earlier
failed native fixture is retained and is not counted as a successful run.

Artifact SHA-256 values (all under the retained directory above):

| Artifact | SHA-256 |
| --- | --- |
| `unit.xml` | `926dbcf15b9c0b9137852dc361792f3dda30024ed2c929de5d3cb2deacc0b5d3` |
| `native-lifecycle.xml` | `1e27772f15b514ff2e5c65025b86e1be002d64a0ffeca63d4669db912ccfb747` |
| `native-store-terminal-r2.xml` | `4dbb3b5d4f58553fb09e179dd932fdf63acff476c08782c753d475fe23fd408d` |
| `dist/kairos_execution_engine-0.1.0-py3-none-any.whl` | `ab5d74e886b50785468296c04ef9ee903ed919f6c0abcc2845ec83e0816e0eb1` |

These are engineering test receipts, not a real venue order history, strategy
profitability claim, owner arm or permission to reuse reserved risk capital.
