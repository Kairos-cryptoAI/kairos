# Kairos: guarded operations engineering — 2026-10-03

This continuation supplements, rather than rewrites, the
[October 2 engineering checkpoint](ENGINEERING-DELIVERY-2026-10-02.md).
The date is Europe/Moscow; native evidence timestamps use UTC.
The final source identity is the signed [current manifest](../config/current-release.json).
These are engineering results, not trading or financial authority.

```text
TECHNICAL_PAPER_READY=false
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
TRADING_AUTHORITY=NONE
```

## Durable operator control

Persistence `568007866d170fbe63fb73a0c798c068dc563e1c` adds an explicitly
opt-in `CONTROLLED_RUNTIME` profile: the original 17 runtime migrations plus
`026_operator_control.sql`. Neither the immutable legacy migration runner nor
the separate 25-migration SIM profile is upgraded implicitly.

Risk `402d377ab0604cc05ea648830d687e2ce73578e2` and Execution
`4c4ddc9898c021ee6d80c4835a3a9d68bed88cc6` require durable account-wide
operator fencing for PAPER entry admission/dispatch. The remote DEV account,
not a local alias, owns the latch. `DISARMED`, `ARMED` and `KILLED` transitions
use exact versions, database-clock expiry and immutable command/admission
records. Stale or killed approval cannot be reused. A committed dispatch claim
precedes the venue call; an unknown outcome is not retried. Protective exits
remain independent of entry arming.

Runtime, operator and migration ownership are checked separately. Unsafe
superuser/owner/operator/write privileges fail closed before PAPER consumers
or publishers start. No operator role or controlled profile was provisioned
on the real primary. The existing PAPER deployment therefore remains guarded,
not automatically deployable after dependency repinning.

Three real PostgreSQL operator tests passed in a disposable, bounded database:
runtime privilege denial (including unsafe accidental grants), concurrent
versions/account aliases, and durable claims/KILL/restart no-resend behavior.
The dedicated bridge and 1 CPU/1 GiB container were removed. This was not an
EVEDEX session or a production KILL exercise.

- Receipt: `D:/Kairos/runtime/operator-control-20261002/20261002T205203Z.receipt.json`.
- SHA-256: `37a890a8c884f04468f5603efc04814e8203e2f10eb5751c67bdd7a4e4be98d6`.

## Production evidence and managed-signing boundaries

Execution includes offline, unwired production-evidence and managed-signing
contracts, ending at preconditions validation, never a LIVE capability.
Fourteen independently interpreted evidence kinds must bind the same PROD
account, adaptive system, policy and exact source context. An alpha assertion
still requires its own sealed 365-future-day/500-natural-close evidence; Trial
15 cannot substitute for it. Manual dollar caps, stop-loss and once-only
nonces remain separate prerequisites.

The signer accepts only fixed EVEDEX EIP-712 message geometry with independently
provided authorization, durable claim, managed backend and signature verifier.
Raw keys, generic signing, withdrawal and provider factories are not introduced.
Strict boolean proof checks and sanitized ambiguous claims have regressions.
The final isolated framework suite passed 46 tests before the operator slice;
the combined execution suite later passed 492 tests. Fake backend tests do not
qualify a KMS/Vault provider, cryptographic custody or a real venue identity.
The actual LIVE startup rejection remains unchanged.

## PAPER atomic recovery: partial native result, not acceptance

The new clone-only controller uses the unchanged frozen runtime runner and one
physical connection/outer transaction for the old runtime suffix and exact
ambiguous row 117625. It adds durable host pre-COMMIT evidence, response-loss
classification and full-history preservation checks. It has no primary apply
mode, consumer restart, lease/cursor reset or outbox drain.

Thirty-seven offline clone/worker tests passed. Hosted Windows temporary-path
aliases are resolved in test fixtures, while the strict production pre-COMMIT
directory guard remains unchanged. One admitted native attempt was bounded to
300 seconds, one CPU/3 GiB clone and a bounded worker. It timed out at
`after_migration_016`. The all-27 legacy clone baseline and rollback checkpoints
after 013, 014 and 015 were accepted; 016 was not accepted. COMMIT, quarantine
and final runtime backup/restore were **not proven**. No retry or resource
expansion followed. The primary stayed stopped and unchanged; owned clone
containers were removed, while the plan and failure evidence were retained.

- Failure: `D:/Kairos/kairos-deploy/backups/paper-runtime-atomic-attempt-2d7226ae315b/failure-9215691996ce.json`.
- File SHA-256: `5d85fde977ab22718629f852bb082ffe0911d122121a4d6bc816a9ab8f0f0289`.
- Result: `FAILED_NATIVE_CLONE_NO_AUTHORIZATION`.

This explicitly does not complete runtime recovery. A separate reviewed proof
design, fresh accepted backup and complete native acceptance are still needed
before any primary change. The prior read-only full-history PASS is historical
evidence, not a renewed current-state permission.

## Telegram preparation and exact recipient correction

The owner selected native Alertmanager and `KairosCryptoAI_bot`. The final alarm
group is `-5155583216`; the corrected test group is exactly `-100447580288`.
Protected token files are never embedded in Git, argv, receipts or the browser.
Qualification journals are exclusive/fsynced and unknown sends never retry.

The previous wrong test-group attempt remains `SEND_OUTCOME_UNKNOWN`; the owner
reported no visible message, which does not retroactively determine the API
outcome. The corrected group stopped before sending. A separate bounded
read-only diagnostic confirmed the bot but returned HTTP 400/API 400
`CHAT_NOT_FOUND`, with getMe=1/getChat=1/send=0. The owner must confirm bot
membership and the exact accessible chat identity. No further send occurred.
The token exposed earlier in chat should be rotated before permanent use.

Pinned native `amtool` accepted the generated synthetic configuration and
routed all 33 actual base/PAPER alert rule names in network-none containers.
The separate optional operational Compose project has no host ports, Docker
socket, DB/trading mounts or business-service startup; its policy remains
disabled pending explicit cadence/source binding. The notifier has 128 MiB,
0.25 CPU and 64-pid bounds. Its tmpfs dedup state is not restart-durable and
its egress bridge is not an endpoint firewall.

Actual Prometheus-to-Telegram firing/resolved delivery, human acknowledgment,
restart behavior and independent host-loss notification are not qualified.
No real alarm service was started.

## Restic: selected offline preparation only

The owner selected standard Restic preparation **without a remote connection**.
Strict policy rejects destination URLs, credentials, enablement and guessed
custody/retention/RPO/RTO/cost choices. The exact accepted PAPER dump, manifest
and signed full-history receipt/signature form a four-file inventory. Inventory
preparation only hashes/verifies contained artifacts; it does not contact the
database, exchange or remote storage.

Only the locked official distribution can enter an optional fixed synthetic
local fixture: signed checksum validation, exact maintainer identity, bounded
single executable extraction and independent verification inside a new private
workspace. Caller-provided verification booleans cannot authorize execution.
The fixed fixture uses random ephemeral password files, literal full snapshot
identity, complete authenticated data check, wrong-password rejection and an
absent restore target. It has no upload, remote initialization, arbitrary file
selection, prune/forget/unlock or readiness mutation.

The initial native attempts failed closed on Git trust, MSYS path mapping,
agent startup and the GPG socket-path length. Their separate failure receipts
and workspaces remain intact; partial key imports were not treated as success.
The final agentless, public-only short-home helper was independently reviewed,
including exclusive-create collision behavior, without rewriting verification
arguments or the original Restic pipeline.

Exactly one fresh public-import check then passed, followed by one fresh native
synthetic fixture and historical inventory check on deploy `d49c7eda...`.
The locked signed distribution was verified before execution. Twelve native
children had twelve verified bounded process-tree cleanups, with a 512 MiB job
memory bound and eight-process limit. The local synthetic file passed encrypted
backup, complete authenticated data check, wrong-password rejection and restore
to a new target with an identical SHA-256. No real runtime data was put into the
Restic fixture. The separate four-file historical inventory passed checksum and
public-key signature verification; it did not renew the old backup's freshness
or authorize primary recovery. There were no new downloads, remote uploads,
database contact or operator-key reads in these final checks.

- Public-import receipt: `D:/Kairos/runtime/offhost-backup/g-44dd93ebbf054b2dbe413bfe079ecd3f/public-import-proof.json`.
- Receipt SHA-256: `7ad93147358020ac6396a5d7f197d5b1b87d6e65408a8719c2f936fab9193de9`.
- Native receipt: `D:/Kairos/runtime/offhost-backup/r-e331782d1825f716/native-proof.json`.
- Receipt SHA-256: `f3c4378080fc50251bc2d0d4da197c60b70cdce60ace921853bef421b13fcb56`.
- Inventory file SHA-256: `e7970a1545b2b5a4fd20768fd1e3db4dd341ee58b79d8e0d3bae75ccc629d60b`.
- Result: `PASS_LOCAL_SYNTHETIC_AND_ACCEPTED_INVENTORY_ONLY`.

This does not prove a database restore or off-host recovery. Off-host status is
`BLOCKED_DESTINATION_UNCONFIGURED`: destination, managed key custody, disaster
recovery, retention and accepted off-host database restore remain unconfigured.

## Updated-source verification

All service dependency pins use the published Persistence/LLM revisions.
The 13 mutable deploy projections/locks contain SHA-only updates; frozen Core,
Backtest, old runner/catalog, Trial 15 and V4/V5 evidence are unchanged.

The native Windows Python 3.11 / uv 0.12.3 gate passed 96/96 checks over all
12 code repositories: 2,944 test passes, four skips, 77 integration deselections
and 12 builds. Published HEAD/origin, source/locks and gate inputs stayed
unchanged before/after. No paid API or trading service ran in this gate.

- Receipt: `D:/Kairos/runtime/windows-gate-20261002/python-3.11-20261002T211751Z.receipt.json`.
- Receipt SHA-256: `67bf031327390d69a2d4fcf0438821afa939bc0030419f63286685e8de00d282`.
- Sanitized log SHA-256: `7365cbf9001c44441164ea8764269a162c433e62a1e0d4188f65942d65942048`.

The Python 3.14 gate also passed 96/96 checks over the same 12 published
package identities, with the same 2,944 test passes, four skips, 77 integration
deselections and 12 builds. This is the native Windows matrix, not a hosted
CI or runtime-recovery substitute.

- Receipt: `D:/Kairos/runtime/windows-gate-20261002/python-3.14-20261002T212920Z.receipt.json`.
- Receipt SHA-256: `fc562f0c58c67209a33802673d900c2d9628cd9b217105593facbaecacc851ce`.
- Sanitized log SHA-256: `6ebd6e9a8fe9f4a99c11bdadf5ba7b1be18256e74e542fb4eb7697d084e32eba`.

Final deployment unittest discovery passed 308 tests with two explicit Windows
privilege-fixture skips on both Python 3.11 and 3.14 (36.797/36.823 seconds).
Twenty-one Restic-focused tests passed per version. Eleven projection validators,
both genuine locked gate environments, seven current-source tests and 18
full-path policy tests passed. Completed native updated-source Docker and
exact-head hosted CI evidence are recorded below.

The exact source revision is deploy
`d49c7eda89aa1fb3425e0b479847707c03625e34`, published with the trusted signature.
Hosted Compose 2.38.2/2.40.3 omits false bind options in JSON; only those reviewed
versions can use that historical encoding. Explicit false remains required for
unknown renderers, and true/unsafe/ambiguous mounts remain rejected. The native
offline version/config inspection closes stdin and has a 45-second deadline;
timeout/nonzero/invalid JSON still fails without retries or skipped validation.
Telegram/API production timeouts and topology are unchanged.

On that exact deploy revision, hosted
[CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37072257527),
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37072256883),
[current-source integration](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37072298367)
and [full-path SIM integration](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37072301708)
all passed. CI covers Windows/Linux Python 3.11/3.14, static/remote/Compose
validation and image builds; image builds do not start PAPER services.

Fresh local Docker gates also passed on that exact revision:

- Current source: seven tests in 2.69 seconds;
  `D:/Kairos/runtime/operator-control-20261002/docker-current-20261002T222400Z-883a2641/receipt.json`,
  SHA-256 `64da26cd463a354203207e3915091958d20a4190f3d66a8f968473b3673386e0`.
- Full path: 23 tests in 14.13 seconds;
  `D:/Kairos/runtime/operator-control-20261002/docker-fullpath-20261002T222505Z-d22f58bc/receipt.json`,
  SHA-256 `80342e9706f66a9ea539523e5f12565b056b6ec1e9f092105a5551ff7b5ee544`.

The full path uses closed bars, Strategy, Router, a deterministic zero-cost
review double, SIM risk and a disposable PostgreSQL simulator. No provider,
exchange or primary mutation occurs. Owned test containers/networks were
removed and source/lock/signature checks passed again after execution. The
synthetic 8,668,621-byte dump is retained, but its restore was not verified and
it is not runtime recovery evidence. Runtime containers had explicit CPU,
memory, PID and tmpfs limits; Linux BuildKit server hard-CPU/cancellation
qualification remains unproven despite bounded Windows CLI jobs.

The preceding local current-gate attempt is retained as FAILED_OR_INCOMPLETE:
`docker-current-20261002T220933Z-f8ebda54/receipt.json`, SHA-256
`f2d13e7efead39015561835608a86346b12bb0440d31a9feaab95dbfe8f42827`.
Its verifier incorrectly expected a populated endpoint NetworkID before the
first start. The correction accepts empty NetworkID only with exact owned
HostConfig/network identity and strictly never-started CREATED state. Running
or exited containers still need an exact populated NetworkID. A separate,
freshly guarded one-ID cleanup removed only that never-started test container;
the old receipt and captures were not rewritten. Thirty-one offline helper
regressions passed; the final helper SHA-256 is
`601d8c07d52e101c8e16d73a752b5ab85560dc6b745590f0885a11a3399fb95a`.

A fresh read-only published-source audit verified all 13 non-meta repositories:
clean tracked main, local origin/main tracking equality, exact trusted signatures,
successful exact-HEAD source CI/integration workflows, and completed exact-HEAD CodeQL
analyses without analysis errors. Successful CodeQL analysis does not assert
zero security findings. Source identities stayed unchanged during the audit.
The meta repository is verified separately after its final signed commit.

- Receipt: `D:/Kairos/runtime/operator-control-20261002/20261002T223241Z.published-source-ci/receipt.json`.
- SHA-256: `37c82a0e24668b5917c6ebd9e9984a93959f2f6a0ce9023ec506f45e20e7537b`.

## Remaining decisions and elapsed gates

No paid provider probes, EVEDEX/canary/LIVE orders, backup upload or UI work were
added by this operations slice. The October 2 cumulative model budget and old
unresolved reservations remain unchanged.

The remaining boundaries are complete atomic runtime proof/primary acceptance,
accessible Telegram receiver/delivery, actual off-host destination/custody,
real EVEDEX DEV qualification, the adaptive system's own sealed economic gate,
independent production security/custody/limits, and explicit owner arming.
None is replaced by green source CI or a local synthetic restore.
