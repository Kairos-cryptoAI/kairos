# Actual Risk-to-Execution composition — 12 September 2026

## Result and exact boundary

Deploy `44be2e233e276c49fb8265bd509d37095cad94db` adds a dedicated test-only
composition and GitHub-hosted workflow. It does not change runtime source pins,
public contracts, trading policy, strategy generators or frozen research files.

- Local Windows: **82 hermetic tests** passed; Ruff, formatting and the locked
  35-package dependency check passed. The existing **60 deploy tests** and both
  source validators also passed.
- [Release-gate CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/34702602271):
  both Windows/Linux hermetic jobs passed. The actual PostgreSQL/Redis
  composition passed: **83 tests, zero skips, 3.57 seconds**, container exit 0.
- [Standard deploy CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/34702602274):
  all **20 jobs** passed for the same revision.

The production packages are installed non-editably from exact published Git
commits. The test checks both installation metadata and actual imported paths:

| Package | Revision |
| --- | --- |
| Core | `91cd95c8e5bd4393ed04606df08c205583092df7` |
| Persistence | `730ff1a878305ffef80a07a615795208a0372091` |
| Risk | `145c3b1deba381a966374867e43c734fdc5e7211` |
| Execution | `641a08045c70f15ab9d7a5b04e54ed0928a71529` |

## What actually ran

A synthetic, explicitly marked readiness receipt armed one test session in a
fresh database. The real arm transaction staged review/allocation messages in
the durable outbox. **RiskService ran its normal consumers and computed the
decision**, rather than receiving a fixture decision. The real durable bus,
PostgreSQL inbox/outbox, Redis Streams, Execution decision consumer, admission
repository, journal, protected FSM and recovery handled that decision.

The only exchange adapter was synthetic; the full Execution sidecar/network
service loop was not started. Real Risk account bootstrap completed before
creating the fresh five-second venue observation. Entry/expiry/risk limits were
not relaxed to make the test pass.

Observed assertions include:

1. A separate PostgreSQL connection sees completed inbox state and required
   decision/lifecycle outbox facts **before** each observed Redis ACK.
2. One injected fault occurs after the Execution PostgreSQL commit, before its
   Redis ACK. Fresh service instances recover, and actual Redis `XAUTOCLAIM`
   reclaims the pending delivery. Only the synthetic message's idle age changes;
   the production reclaim threshold is unchanged.
3. Two additional duplicates have new Redis IDs. The test waits for those exact
   IDs and consumers, not an aggregate ACK count. Completed inbox state,
   attempts, result, timestamps, lease and payload hash remain unchanged.
4. There is exactly **one Risk decision, one entry call and one dispatch claim**.
   The immutable intent/exit plan, 1x leverage and deterministic risk caps remain
   checked. Stop and target are created through the real FSM.
5. After admission is stopped, timeout recovery closes the existing position
   even when the restarted engine has no entry-authority scope file. The final
   trade is `FLAT`, effects are resolved, inbox/outbox are complete and checked
   Redis pending lists are empty.
6. Late task and resource-close failures are checked before the PASS receipt is
   printed. The successful run observed nine ACK boundaries and nine lifecycle
   facts. Those counts are fixture evidence, not real trading throughput.

## Isolation and retained evidence

The job ran on a fresh hosted Ubuntu VM, not on the operator's paused Docker.
It used an internal-only network, no host ports/mounts or real secrets, fixed
synthetic credentials, bounded resources, a 180-second runtime wait and a
25-minute overall job limit. PostgreSQL identity, empty public schema and empty
Redis were checked before the first migration or fixture write.

PostgreSQL used tmpfs and Redis persistence was disabled. This proves
**application-service restart while the data services remain alive**. It does
not prove power-loss recovery, database/Redis-container restart or venue recovery.
The workflow did not stop the data services before diagnostic capture.

All five artifact captures completed. Retained local evidence:
`D:\Kairos\runtime\release-gate-ci-20260912-44be2e2`.

- Gate image: `sha256:6f10695a5078f905926b19286391c8eeb40361412898106a1e2ac7598bbec2b4`.
- Synthetic PostgreSQL dump SHA-256, independently checked after download:
  `1416e44dc32b1dd5ca2f93c6b42bd71964f055396f4ac4be1fa1fceff7a7dec2`.
- `pipeline.log`, `services.log`, `containers.json`, `images.json`, exit status
  and per-capture status accompany the dump. The dump is diagnostic preservation,
  **not** an additional successful restore drill.

## Local post-SSD execution — 16:33–16:34 UTC

After the verified official Docker-data relocation, the same unchanged harness
ran once against a new local `kairos-release-gate-20260912` namespace. Preflight
found no prior project containers, network, volumes or gate image. The captured
deploy HEAD was `bd99d6612bce2e2520082889c4d4677da17f5d0b`; its Quant-only pin
update does not change the four installed gate dependencies above. All eleven
harness file hashes matched before and after the build/run.

Result: **83 tests, zero skips, 3.14 seconds, exit 0**. The real Risk/Redis/PG/
Execution composition observed nine ACK boundaries, nine lifecycle facts, one
entry call and unchanged inbox state after exact duplicate delivery. The same
synthetic-venue and application-restart limitations apply; this is not a real
DEV session or a storage crash test.

Evidence directory:
`D:\Kairos\runtime\release-gate-local-20260912T163350Z-9a6cb34a`.

- `result.json`: SHA-256
  `2f183b2b751594d6dddfff8f60961b728e95cf6cf68766e8955dba895b9bc13e`;
- gate image:
  `sha256:cafde369d8b80b8ec071bf7dfce6bb8a773d2caadd295c56f2df65838e738a90`;
- binary PostgreSQL diagnostic dump: 213,705 bytes, SHA-256
  `40eb6322a21fe0013b5a7b536f51c791a88207bcc50c3dcbe44d8925905c289f`.

Logs, resource/source identities and the dump were captured **before** cleanly
stopping the three newly created containers. The twenty pre-existing containers
remained unchanged/stopped; no project volumes were created. The new image,
internal network and stopped containers are retained. PostgreSQL tmpfs contents
are ephemeral and were lost on stop; their diagnostic dump is retained, not
restore-qualified. `pg_dump` emitted its Timescale circular-constraint warning,
which is preserved and was not silently treated as a restore success.

A preceding helper attempt failed during read-only preflight before any build,
container creation or pipeline execution. Its separate diagnostic directory is
retained. Fixing that helper's PowerShell output handling did not rerun the
pipeline: the successful run above was its only actual local execution.

## What this does not establish

The test does not exercise the full closed-bar → Strategy → Router → LLM review
path; authenticate with EVEDEX; verify actual book/fill/slippage semantics;
complete the five-symbol canary suite; accumulate real 24-hour/seven-day uptime;
establish profitable alpha; or implement the durable SIM trading runtime.
Provider/API budgets, frozen strategies, sealed evaluation gates and the current
`REJECT_ALL` policy are unchanged. `PAPER_QUALIFIED`, `ALPHA_READY` and
`LIVE_READY` remain **false**. Current-release technical readiness remains
unproven until the remaining scoped gates, including runtime recovery and the
wider pipeline, are complete. The local post-SSD gate is now completed within
the limited composition boundary described above.
