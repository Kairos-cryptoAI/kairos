# Isolated full-path simulator gate — 20 September 2026

## Result and boundary

The current runtime source set passed one local, disposable Docker proof of
the following causal path:

```text
sealed closed bars -> Strategy Engine -> Router -> local deterministic review
  -> SIM-only Risk -> durable simulator controller
```

The gate completed with **20 passed** tests in **9.46 seconds**.  It is solely
an engineering receipt: all results are `SIMULATED`; it used no account,
credential, EVEDEX endpoint, LLM provider, paid feed, host port, host volume,
or durable host database.  It cannot approve a strategy, PAPER, alpha, or
LIVE.

## Reproducible local evidence

| item | value |
| --- | --- |
| Date | 2026-09-20 UTC |
| Docker server | 29.7.2 |
| Disposable Compose project | `kairos-sim-full-path-gate-20260919-r1` |
| Database | internal-only TimescaleDB on tmpfs |
| Static source/Compose validation | passed, including remote immutable-source verification |
| Compose configuration SHA-256 | `293a509293ee866533ad74eba7f35e4838929e0bf02f8dd42cf8a4edbde3c8e6` |
| Captured Compose log SHA-256 | `f15ec2496d135323e444028c13026c6918cdf2502c3828df9dbb337d1337125c` |
| Log directory | `D:\Kairos\runtime\sim-full-path-gate-20260920T083100Z` |

The two test containers and their one internal network were removed only after
the exit status and captured files were checked.  The gate creates no named
volume.

Its installed source locks were exactly:

| component | revision |
| --- | --- |
| Core | `4832a407bb94eb82abee84fe5c8a1de828c37833` |
| Persistence | `c89bb31f9425e81e5d77edc6a7e5a871a017af6c` |
| Strategy Engine | `765e5ed2599daa64dcb718de228441044e24d821` |
| Router | `c634355c1725ea41d4cbd9130795697ec71c94a5` |
| LLM contracts/review boundary | `5dff1e7597cb9c124312dcd42247afe649005eb5` |
| Aggregator | `cb7b0261d164439ab1182d99e9c91c5a4b93b1ea` |
| Risk Manager | `319a5f993047b5492e15040a8a6bd4c000ea113d` |
| Execution Engine simulator controller | `cfcba17519952bcbdd6ef6e3b2386b6474c89b72` |

## Assertions covered

- The frozen Strategy Engine produces byte-identical `StrategyIntent` output
  for the same sealed bar sequence.
- The Router preserves the intent; the Aggregator boundary is exercised with a
  deterministic zero-cost local `ALLOW` or `VETO` response, never a provider
  client.
- SIM-only Risk writes approved and rejected evidence without changing any
  PAPER/LIVE readiness or strategy allow-list.
- Sealed top-N book evidence retains raw-frame hashes and chain continuity.
- The simulator records a durable entry, restarts its application-side
  controller, rejects duplicate entry work, and resolves the ambiguous exit
  bar conservatively through the stop path.
- The terminal trade, journal chain and prepared-command inventory are checked
  after the restart; the VETO path creates neither admission nor command.

## What remains deliberately unproven

This gate is not EVEDEX authentication, book/liquidity, reconciliation,
slippage, rate-limit, protective-order, canary, or soak evidence.  It also does
not call the real LLM/feed providers or establish strategy alpha.  Runtime
PostgreSQL catch-up/recovery is a separate guarded contour.  Therefore the
current state is unchanged:

```text
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
```
