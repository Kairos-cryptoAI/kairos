# Runtime and production execution continuation — 2026-10-23

This is engineering evidence, not a completed real-money launch, an alpha
claim, a wallet authorization or a replacement for frozen research evidence.
Every readiness flag remains false; `STRATEGY_POLICY=REJECT_ALL`.

## Owner scope and capital preparation

The owner clarified that “all” refers to the small balance of the main wallet,
not a separate test wallet, and delegated selection of the daily-loss rule.
The preparation rule is a daily stop of **1% of the capital frozen at a future
manual arm**, 1x leverage, no more than 0.25% risk per trade and 1% aggregate
open risk. The 1% daily rule is a conservative experimental setting, not a
demonstrated optimum or a guarantee against slippage/larger losses.

This does not transfer or deposit wallet funds, select the owner private key,
issue an arm, increase any limit dynamically, or permit trading. Exact dollar
limits still have to be frozen from an accepted current account observation
at the future arm. Only the separately delegated signer is a custody candidate.

The previous long-research LIVE contract has not been weakened. Whether to
prepare a separate owner-funded limited experiment before its 365-day/500-trade
research gates is an explicitly pending owner decision, not inferred approval.

## Implemented production composition

Signed Execution commits:

- `9f89d971c584f6ff0328ac4d1bf8893029c96f41`: exact-scope composition of the
  existing PostgreSQL state/claims, signing policy, managed signer and one-use
  wire dispatcher; adds a public read-only authority inspection API.
- `7c731a4e2302c4a21c1f1f4316452a6c9d808957`: account-bound GET-only PROD
  observation with local per-component retrieval bounds and content digests.
- `db61ac25b8d75e5eaab1d1f5d9c2f715ae988e3b`: explicit JWT/API-key credential
  alternatives; API keys use the official `x-api-key` header, without wallet
  login or signatures.
- `93ff079f1aae1b8317d1bfc061ab7abd8c6987c3`: zero funding remains observable;
  it never creates trading capital or readiness.
- `3fa6dd2a358b9fd604059fb74bf711e346f315ce`: normalize documented list
  envelopes before cross-component balance/order/position checks.

The composer intentionally returns `TRANSPORT_RESPONSE_UNRECONCILED`, never a
fill or a completed lifecycle. Cancellation/timeout/unknown outcomes retain
their durable claims and reservations. Unsupported effects refuse before a key
operation. The existing LIVE factory refusal remains in place.

The new observation is explicitly **not an atomic venue snapshot or
authoritative exposure**. It does not emit `ExposureSnapshotV1`, release risk
reservations, approve a decision, or create execution authority. Original HTTP
bytes are not claimed by hashes of canonical parsed JSON.

## Actual PROD account observation

The first finite read, at Execution `93ff079`, failed closed after seven GET
attempts. Its original claim/report and script are retained unchanged under
`D:/Kairos/runtime/production-account-observation-20261023`.
The schema review then exposed a concrete wrapper-normalization bug; a new
offline regression reproduces the documented `list` envelopes.

One new, finite observation after that fix passed at Execution `3fa6dd2`:

| Fact | Observed result |
| --- | --- |
| Completed time | 2026-10-23 07:24:23 UTC |
| Authenticated account | Matches the previously retained UUID/auth-ID/wallet binding |
| ID namespaces | Numeric `exchangeId` explicitly mapped to that UUID; old receipts not rewritten |
| Private API attempts | 7 GETs, no automatic retries |
| Captured components | Account-before, available balance, positions, opened orders, TP/SL, account-after |
| Capture interval | 07:24:21.074238–07:24:22.820619 UTC |
| Funding / available balance | Both positive in this observation |
| Nonzero positions / opened orders / active-or-waitorder protections | 0 / 0 / 0 |
| Wallet signatures / orders / transfers / paid-provider calls | 0 / 0 / 0 / 0 |
| Atomic/current-state authority | Not established |

The endpoint also returned historical/zero-quantity records. Their presence was
not misreported as currently open exposure. No account position/order was
changed. No original key values or raw authenticated headers were exported.

The successful private directory is
`D:/Kairos/runtime/production-account-observation-20261023-r2`.
Its entrypoint and report are GPG signed. Normalized facts and canonical source
content hashes are retained; full `/me` replies and source key-file content are
not retained by this observation.

`observation.normalized.json` SHA-256:
`c40182829ddcfa3dc19847a3fc870de8855843d7c3a4465a041916b687212e2f`.

## Non-trading runtime successor

The old Oct21 serving process exited with
`REDIS_RECOVERY_DEADLINE_EXCEEDED` / pending-read `TimeoutError`. Its failed
status and the stopped databases/queues remain preserved. A roughly 59-second
reported transport failure against a shorter recovery budget does not, alone,
prove the root cause. No arbitrary timer increase or claim of a root-cause fix
has been made.

Signed Deploy commits `dc453b759c6c7700b8207e655ea6e2176a563f40` and
`56a7130ceeabd23742879894eef2aa61724ad7f3` add a create-only, separately owned
successor wrapper and a collision-checked dedicated bridge. It reuses the
accepted historical 18-migration source profile and unchanged native
seed/catch-up/restore/qualification/serve pipeline. This is not a claim that the
historical source profile equals all current release heads.

The accepted baseline dump hash is
`2408db1335dc856122750e4604f14a436184f54a7f4ffab22bc35eb69747a7bc`.
Only its verified 173,164 historical closed bars seed the new epoch; public
Binance catch-up revalidates the later history. Old outbox/FIFO state is not
copied or reset.

The first new owner `4c71362d73764ca7ad73fc4de09d0836` failed before creating
resources because Docker's predefined address pools were exhausted. Its
create-only failure remains retained. The reviewed repair permits only that
exact hash-bound pre-creation failure as predecessor, independently proves no
owner-labelled resources exist, and never adopts its owner. It creates a new
bridge `10.254.251.48/28` only after checking all Docker IPAM subnets and Windows
IPv4 routes. No existing Docker network was deleted or reconfigured.

A later admission refused an incomplete process inventory before creating a
run directory; a new read-only inventory subsequently completed successfully.
The refusal was not converted to an empty-process assertion.

The admitted successor is owned by `1ec512799b23422190a1f3360ba60996`, started
from signed, green Deploy `75c4b1ad1cff5aa723a0376bfa422eea1d3fa947`, under
`D:/Kairos/runtime/nontrading-successor-20261023/run-1ec512799b23422190a1f3360ba60996`.
The finite controller completed at 07:44 UTC with
`PASS_NONTRADING_RUNTIME_EPOCH`. No second live controller was launched.

Accepted native facts:

- Two bounded historical catch-up batches added 242,230 real closed bars to the
  verified seed. The audit backup contains 415,394 bars across all five symbols;
  XRP retains its one-bar-later historical start rather than an invented bar.
- The fresh binary dump was restored into the separate owned clone. All 32
  public tables and their ordered digests, sequences and history anchors matched;
  native `pg_amcheck --heapallindexed --parent-check --rootdescend` exited cleanly.
- A final 160-bar audit-only catch-up bridged the time spent verifying the clone.
  Qualification proved same-ID Redis acceptance replay, duplicate delivery
  acknowledgement without a new inbox row, and hash-conflict refusal.
- The serving worker passed a drained same-container restart. A subsequent
  independent observation at 07:46 UTC found eight serving cycles, 20 completed
  inbox records, equal advancing five-symbol watermarks, fresh sources and zero
  pending outbox, unresolved inbox, uncompleted publications or Redis transport
  failures. The existing owner-bound metrics parser independently reported
  `running`, non-stale. This is a bounded observation, not a long uptime claim.
- Both source and restore clones are stopped and retained. The exact five old
  failed/stopped container identities and historical lease were unchanged before
  and after the controller. Old data, queues and partial failures were not reset.

The create-only final receipt is
`runtime-epoch-successor-receipt.json`, SHA-256
`be08ab9803836132178c3f684af928b95d5ba44e7c77df17996adfb2d6deff89`.
Its detached GPG signature verifies against
`40AF365C6682B73D056A6A274DBFF6B65BE9F827`.
The retained `epoch-history.dump` SHA-256 is
`e65066d5a537437f8faaea20a1d3d80bcc25d560899e6ae45e5ec886d8e801b8`.

The result restores an independently owned **historical-profile non-trading
runtime**, not full production execution. It explicitly records
`root_cause_fixed=false` and `production_qualification=false`. It does not prove
that the old Redis failure cannot recur or deploy the current production-state
schema. Existing boot and Telegram tasks remain bound to their earlier owners;
no automatic startup/notification qualification for this successor is claimed.

## Checks and remaining engineering boundary

- Execution Windows regression suite: 785 passed, one skipped, 48 opt-in native
  integration tests deselected, seven subtests passed. Native component gates
  are separate hosted CI evidence, not real EVEDEX order acceptance.
- Execution Ruff, format and mypy passed; Bandit passed for the final production
  composition and observation source set, including the normalization fix.
- Deploy: 1,094 offline tests passed (eight skipped), including 30 successor
  admission/retention/network tests. All eleven deployment validators passed.
- Active source pins/locks are updated without altering frozen campaigns.
  Current-source identity verification must be repeated after the final report
  commit; a green earlier source set is not silently promoted to a new one.

Hosted Execution and Deploy gates passed for `3fa6dd2` and `626a3be` respectively.
Meta CURRENT offline verification passed on Windows and Linux for `1a9ab2e`.
The separate native-campaign test failed there with a swallowed evaluator error
in the veto/conflict cases. Signed test-only commit
`cc1e97a537348c09aff0ba6b35556310e3566c82` extends the existing sanitized
exception-line/class diagnostic to every case; no evaluator, timing bound,
expected result or strategy changed. Its Python 3.11 and 3.14 native jobs passed
in run `39919682895`. This pass is not a proven root-cause fix for the earlier
intermittent failure.

Actual remaining production execution work includes accepted PROD signing
chain/domain identity; independently sourced coherent operator/risk/exposure
state; exact effect/parent/fill/protection lifecycle reconciliation; and an
append-only authoritative terminal disposition before reservations can be
released. Current REST observations and successful HTTP dispatch are not
substitutes. The unaccepted signer and guarded factory must not be bypassed.

The official SDK still exposes a chain mismatch with the installed historical
SDK; a frontend fallback or API key read does not settle backend signature
acceptance. The previously authorized support request is retained; no duplicate
outreach or test order is sent here.

No fresh-news CURRENT verifier, paid model, PAPER/LIVE service, legacy/R7
consumer, runtime reconciliation or real-money execution was started.
