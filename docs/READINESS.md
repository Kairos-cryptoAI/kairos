# EVEDEX DEV PAPER readiness

_Evidence boundary: 2026-08-23. This document records capability and permission separately._

## Current markers

```text
TECHNICAL_PAPER_READY=true
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
```

`TECHNICAL_PAPER_READY=true` means only that the exact revision set below passed its declared
code, contract, parity, recovery, local Windows, Docker integration and GitHub CI gates. It does
not assert that EVEDEX credentials work, that an order was placed, that the venue met its service
thresholds, that a strategy is profitable, or that PAPER/LIVE is authorized.

`PAPER_QUALIFIED=false` is the operational truth until real EVEDEX DEV evidence completes the
ordered qualification ladder. `ALPHA_READY=false` is independent: all existing strategy sleeves
remain rejected by the unchanged offline evidence. `LIVE_READY=false` blocks EVEDEX PROD,
production signing material and real funds regardless of any other marker.

## What technical readiness covers

- strict `extra=forbid`, immutable V1 contracts for closed bars, strategy intent/review, venue
  quality, risk decision, lifecycle event and reconciled account state;
- byte-for-byte Strategy Engine parity between frozen backtest and runtime fixtures;
- gap/reorder/conflicting-bar rejection and REST recovery behavior;
- candidate review limited to `ALLOW`, `VETO`, `DEFER` and priority, with no intent mutation;
- loss-at-stop sizing with 0.25% per-trade and 1% aggregate open-risk ceilings;
- EVEDEX DEV profile/account/symbol/basis/liquidity gates and `NEXT_BAR_MARKET` expiry;
- durable protected lifecycle, partial-fill handling, stop-before-target ordering, exit-race
  serialization, mutation journal and restart recovery barrier;
- official `@evedex/exchange-bot-sdk` 1.2.11 sidecar under Node 22, with no listener and no
  autonomous mutation retry;
- isolated `kairos-paper` Redis/TimescaleDB/secrets/volumes, fail-closed Compose validation,
  monitoring, backup/restore and recovery tooling;
- fault injection, race tests, local Timescale integration, Node tests/audit, image builds and
  green CI for the pinned revisions.

Any change to a pinned revision invalidates this technical marker until its dependency pins,
lockfiles, local gates and CI are revalidated.

## Operational qualification ladder

These gates are ordered. A later gate cannot compensate for a failed or missing earlier gate.

| gate | acceptance evidence | state |
| --- | --- | --- |
| 1. EVEDEX DEV read-only | real SIWE/auth and reconciliation; no unresolved Binance gaps; availability ≥99%; p95 absolute basis, spread and slippage ≤25 bps; book age ≤5 s; timestamp skew ≤2 s over a complete 24-hour window | `PENDING` |
| 2. Manual technical canary | 1x, exact venue minimum quantity, one global active canary; each BTC/ETH/SOL/BNB/XRP completes a protected round trip; the set covers limit/cancel, stop, target, timeout and restart recovery | `PENDING` |
| 3. PAPER soak | seven elapsed days of data/reconnect/auth/recovery with no duplicate order, unknown lifecycle state, unresolved mutation or unprotected exposure | `PENDING` |
| 4. PAPER qualification review | reviewed TCA, shortfall, venue semantics, recovery evidence and documented limitations | `PENDING` |

Until Gate 1 passes, the maximum permitted state is read-only EVEDEX DEV observation. Gate 2 is
one explicitly armed, bounded session; it does not start an automatic strategy and does not call
OpenAI, DeepSeek or X. Passing all four gates can set `PAPER_QUALIFIED=true`, but cannot change
`ALPHA_READY` or `LIVE_READY` by implication.

## Separate alpha and provider gates

Automatic PAPER remains disabled because the Strategy Engine allow-list is empty and all five
existing sleeves are `REJECTED`. A future strategy must be a new frozen revision and pass the
offline promotion gate before `ALPHA_READY` can change. The historical reports and their
`REJECT_ALL` decisions are not recalculated or reinterpreted by this technical milestone.

LLM/feed qualification is shadow-only and separately capped by the shared durable budget ledger:
OpenAI `$12`, DeepSeek `$1`, X `$2`. Safety requires 100% schema-valid review output, zero
`ALLOW` for deterministically forbidden cases, byte-identical intent preservation, completion
before entry deadline and no budget overrun. Its economic value is later measured as the same
strategy with and without the review overlay; it is not inferred from model intelligence.

## LIVE boundary

`TradingMode.LIVE` is a startup error in this release. `KAIROS_DRY_RUN=false` is also a startup
error and never enables PAPER or LIVE. LIVE requires, at minimum, a passing alpha revision,
qualified PAPER evidence, a separate real-funds review, managed KMS/Vault signing, encrypted
off-host backups and production-specific limits. No current Compose overlay grants that
authority.

## Reviewed revision set

| repository | commit |
| --- | --- |
| `kairos-core` | `a4f427cdd44184fac62a842320133ac5a3e11fbe` |
| `kairos-llm` | `0777bbbcc541e2ac95d2fe965c1c2201845de17c` |
| `kairos-persistence` | `e36a3c01aa8aa3847bfbc8fa42eb4f98794d28a5` |
| `kairos-strategy-engine` | `c1bfd51e6efb7942a583196751b89e4c22a4a5e6` |
| `kairos-backtest` | `4ccc27f04b82787b8815b6df28128f4d88d978ab` |
| `kairos-quant-scouts` | `d71d34db569e9441842f1ef4d6c9cfd8628aaea0` |
| `kairos-text-scouts` | `2d53cd555f6dcf6456161a694a16023a59f75e19` |
| `kairos-router` | `25a33e37902c00c6bcd65bd7774a819893b67523` |
| `kairos-aggregator` | `75cb3cfc4b0ddde4805b3e5b460a842c638314c3` |
| `kairos-macro-strategist` | `65c81efd6010f237a22430a87b816dbf3891e21c` |
| `kairos-risk-manager` | `d311872438c35b0eed76fba1eec799ac5999a107` |
| `kairos-execution-engine` | `de168290a9331accaf4c3aa2b62407b5adf7c614` |
| `kairos-deploy` | `e6223f169baa2284ca3809c9c21de4d7792d5885` |

The meta-repository's own revision is the commit containing this file.
