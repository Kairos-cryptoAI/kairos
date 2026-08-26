# Kairos — Project Status

_Organization: [Kairos-cryptoAI](https://github.com/Kairos-cryptoAI) · updated 2026-08-26_

## Summary

The strict Strategy Parity → EVEDEX DEV PAPER code path is implemented on `main`: complete
closed-bar contracts and recovery, one shared pure Strategy Engine for research/runtime,
immutable LLM review, deterministic loss-at-stop risk, continuous venue-quality facts, a
protected trade FSM, official EVEDEX SDK sidecar, durable recovery and an isolated PAPER stack.

Kairos remains **pre-production**. The four readiness markers intentionally make four different
claims:

| marker | value | scope |
| --- | --- | --- |
| `TECHNICAL_PAPER_READY` | `true` | exact pinned code/integration revision set after local Windows, Docker and GitHub CI gates |
| `PAPER_QUALIFIED` | `false` | real EVEDEX DEV auth/canary and elapsed 24-hour/7-day evidence are incomplete |
| `ALPHA_READY` | `false` | no strategy revision has passed offline promotion; `REJECT_ALL` remains active |
| `LIVE_READY` | `false` | LIVE startup, PROD endpoints and real-funds authority remain blocked |

The first marker is not evidence of exchange correctness, profitability, a completed canary or
an elapsed soak. The exact revision/evidence boundary is in [READINESS.md](READINESS.md).

## Repository state

| repository | implemented state | remaining boundary |
| --- | --- | --- |
| `kairos-core` | strict `ClosedBarEventV1`, intent/review/venue/risk/execution/account contracts; explicit DRY_RUN/PAPER/LIVE modes | any future contract revision requires a new version, never silent field reuse |
| `kairos-llm` | DeepSeek Flash and GPT-5.6 Luna/Terra/Sol routing, strict schemas and durable cost hooks | shadow corpus quality, latency, quota and availability qualification |
| `kairos-quant-scouts` | delayed double-REST-finalized Binance 1m bars, provisional WS isolation, gap recovery, funding fallback, indicators and scheduled EVEDEX quality facts | complete 24-hour observation after EVEDEX restores two-sided liquidity across the required universe |
| `kairos-strategy-engine` | pure generators shared by backtest/runtime; deterministic fingerprints and parity fixtures | every current sleeve is `REJECTED`; a new revision must pass offline promotion |
| `kairos-text-scouts` | GDELT/RSS and official X API, durable cursors/budgets, local filter and DeepSeek fallback | paid shadow freshness, source quality, latency and quota qualification |
| `kairos-router` | immutable candidate-specific NORMAL/CONFLICT route plus isolated legacy FSM | paid review path remains shadow-only while alpha is rejected |
| `kairos-aggregator` | strict `ALLOW/VETO/DEFER` review with immutable intent and no automatic paid retry | frozen-corpus safety/quality and latency qualification |
| `kairos-macro-strategist` | account-aware allocation/shock context and durable publish/ACK | shadow quality and durable long-horizon analytical histories |
| `kairos-risk-manager` | PAPER-only DEV admission, 0.25%/1% loss caps, reservations and manual canary authority | real reconciled-account and venue inputs during controlled DEV qualification |
| `kairos-execution-engine` | official SDK 1.2.11 sidecar, SIWE/auth, protected FSM, atomic public facts and crash recovery | authenticated DEV semantics and protected canary evidence; LIVE disabled |
| `kairos-persistence` | inbox/outbox, bars, decisions, lifecycle/effects, TCA, equity, budget and readiness metrics | retention sizing and encrypted off-host backup policy |
| `kairos-backtest` | imports exact Strategy Engine generators; causal replay and unchanged fail-closed reports | profitable new revision, clean data, historical funding and real-venue TCA calibration |
| `kairos-deploy` | pinned isolated PAPER, source-identity-bound images, deny-by-default secrets/mounts/egress, monitoring and a passing clean backup/restore drill | dedicated EVEDEX DEV credentials, complete 24-hour/canary/7-day evidence; future managed KMS/Vault for LIVE |
| `kairos` | cross-repo manifest, Windows-first runner and current architecture docs | keep manifest/ADRs synchronized with `main` and pinned dependency revisions |

Test counts are intentionally not frozen in this document. The meaningful gate is that each
repository's declared checks and supported Python/Windows matrix pass for the reviewed commit.

## Implemented cross-service flows

- Quant emits canonical complete closed bars, restores REST gaps and blocks a symbol on unresolved
  gap, reorder or conflict. Strategy Engine turns those bars into deterministic intents using the
  same pure code imported by backtest.
- Router preserves the immutable intent while selecting a review tier. Aggregator can return only
  `ALLOW`, `VETO`, `DEFER` and priority; any timeout/error becomes terminal `DEFER` without a
  second paid call.
- Quant continuously records scheduled Binance/EVEDEX observations. Risk requires a fresh
  executable DEV book, reconciled `AccountSnapshotV2`, compatible allocation and no conflicting
  symbol position/order before applying loss-at-stop sizing.
- Execution publishes reconciled account snapshots at startup, periodically and after activity.
  A newer reconciliation failure revokes prior authority; startup recovery forces snapshots
  untrusted until effects, positions, orders and TP/SL are reconciled.
- A first or partial fill is protected with a reconciled stop before target creation. Entry expiry,
  stop, target and timeout converge through a durable per-trade FSM and database lock.
- Every Redis-consuming service records inbox ownership and atomically commits required domain
  state plus outbox messages before acknowledging the stream delivery. The outbox dispatcher
  retries independently and dead-letters bounded failures for operator review.
- Execution records each external venue mutation as `PREPARED` before submission. Startup
  recovery reconciles unresolved effects under a database advisory lock; EVEDEX protective
  orders are reconciled by authoritative parent linkage before new risk is accepted.
- The PAPER exporter derives missing-poll availability, account age, inbox leases, unprotected
  exposure, auth age, durable mutation reserve, reconciliation drift and execution shortfall from
  durable facts. Backup/restore compares critical row counts and public event sequence.
- `kairos-paper` is isolated from the legacy stack and from paid Text/LLM services. Its strategy
  allow-list is empty; a single manually armed `technical-canary@1` is the only pre-alpha path.

## Modernization and verification

- `uv` 0.12.3 is required and `uv.lock` is committed in all twelve Python repositories.
- `.python-version` declares 3.11; Linux CI verifies 3.11 and 3.14, with a Windows job.
- Internal Git dependencies are pinned to full reviewed SHAs rather than floating branches.
- Dependabot configuration covers Actions and Python dependency updates.
- `main` is authoritative; multi-repository changes land in dependency order after dependent
  SHAs settle and their consumer lockfiles are verified.
- [`scripts/Test-Kairos.ps1`](../scripts/Test-Kairos.ps1) runs the equivalent lock, lint,
  format, mypy, Bandit, network-free pytest and build gates locally without Docker.

## Offline strategy validation and promotion evidence

The campaign freezes one candidate before promotion evaluation:
`confirmation_bars=12`, `minimum_hold_bars=48`, and `minimum_confidence=0.67`. Official Binance
Futures monthly 1m archives for the 12-month research interval and untouched July holdout are
audited against their SHA-256 sidecars and ZIP CRCs. The broader upstream inventory is also
audited fail closed; a source anomaly, gaps, or incomplete coverage remains a promotion blocker
even when the replayed window itself is available.

Signals are formed only from closed candles, scheduled at the first eligible subsequent open,
and capped by the previous closed candle's volume. This avoids same-bar price or liquidity
look-ahead. Actual historical funding was unavailable and is reported as unavailable; an
assumed stress rate does not satisfy the historical-funding gate.

| evidence | baseline | stress |
| --- | ---: | ---: |
| 12-month research replay | -4.231727849843687% / 803 trades | -9.763199273155571% / 804 trades |
| untouched July promotion OOS | -1.075965871769744% / 69 trades | -1.5781050811020259% / 69 trades |

Rolling folds are post-selection diagnostics and must not be described as OOS. Only the
untouched July interval is promotion OOS: its buy-and-hold benchmark was
+6.828606504564661%, and zero of five symbols had positive strategy returns. The resulting gate
is `needs_revision` with `real_api_allowed=false` because of insufficient OOS trades,
non-positive return and expectancy, benchmark underperformance, unavailable historical funding,
non-positive sensitivity performance, and upstream anomaly/gaps/incomplete coverage. This is
offline research evidence, not live qualification. The governing boundary is
[ADR 9](adr/0009-offline-strategy-promotion-gate.md).

### Subsequent development-only screens

The isolated `orderflow_volatility_expansion_v1` screen evaluated `IMPULSE`, `PERSISTENCE` and
`FLIP_RELEASE` on reused July-December 2022 `RESEARCH/FIT` data. It was designed to test whether
causal five-minute taker-flow expansion could add trade frequency without weakening the
fail-closed economics gate. `PERSISTENCE` did supply 387 baseline and 301 stress trades, but its
net returns were -2.9005% and -3.2540%. All six trial/scenario cells had negative expectancy and
profit factor below 1.0, so the fixed decision was `REJECT_ALL` and every promotion, shadow and
live permission remained false.

This is useful negative evidence: frequency itself is no longer the primary constraint, while
the standalone post-expansion continuation signal has no demonstrated net edge. The result is
strictly development diagnostics, does not alter the frozen promotion decision above, and did
not invoke an LLM, external API or real order. Full methodology, checksums and artifact hashes
are in the
[order-flow report](https://github.com/Kairos-cryptoAI/kairos-backtest/blob/main/reports/orderflow-screen/REPORT.md).

The third frozen regime/retest family evaluated structural reclaim, flow reacceleration and
absorption reclaim on reused December 2023-June 2024 `RESEARCH/FIT` data. Its complete audited
five-symbol slice contained 1,533,600/1,533,600 expected one-minute rows. The stacked regime,
expansion, retest and admission funnel reduced 41,741 breakout candidates to 12 structural
intents, two flow-reacceleration intents and no absorption intents. Only one baseline trade
executed; stress admitted no trades. The XRPUSDT trade lost $15.49 net (-0.015492%, -1.63R),
and every required frequency and positive-economics gate failed. The fixed decision is
`REJECT_ALL`; promotion, shadow operation, live trading and real API use remain disabled.

This remains development diagnostics on reused research data, not OOS or promotion evidence.
Trials 7-9 are consumed and must not be rerun or retuned against this interval. A fourth
threshold variant must not be created: the next candidate must change the signal structure
while preserving cost-aware admission, and its cumulative lineage must be frozen before the
remaining selection window is inspected. Full methodology and integrity evidence are in the
[regime-retest report](https://github.com/Kairos-cryptoAI/kairos-backtest/blob/main/reports/regime-retest-screen/REPORT.md).

## Remaining limitations

1. **Real EVEDEX DEV behavior is blocked before auth.** The SDK/SIWE path, journal and recovery
   logic are implemented and the exact image contains SDK 1.2.11, but the dedicated DEV API key,
   signing key and confirmed remote account identity have not been supplied. Auth refresh,
   reconciliation, TP/SL states, rate-limit semantics and ambiguous network outcomes therefore
   have not passed the controlled DEV sequence. No canary result is recorded and no real-funds
   order is permitted.
2. **The 24-hour venue gate is externally blocked.** On 2026-08-26 EVEDEX DEV listed all five
   required contracts as `trading=all`, but SOL, BNB and XRP returned zero bids and zero asks;
   only BTC and ETH had executable books. Scheduled poll accounting records these failures, so
   the required 99% five-symbol availability cannot pass until the venue supplies liquidity.
   Binance stable-bar, funding and depth probes passed for all five symbols, but the full elapsed
   basis/spread/depth/slippage qualification remains incomplete.
3. **The canary and seven-day soak are pending.** Each of BTC, ETH, SOL, BNB and XRP still needs a
   protected DEV round trip, while the complete set must cover limit/cancel, stop, target,
   timeout and restart recovery. The subsequent seven-day data/reconnect/auth/recovery soak has
   not started.
4. **External LLM/feed qualification has started but is not a soak.** One bounded X request
   authenticated, read one User and ten Posts for `$0.060000`, and observed rate headers; those
   Posts were older than the 30-minute freshness gate. One structured call passed on each model
   route: DeepSeek Flash, GPT-5.6 Luna, Terra and Sol. The modeled LLM cost was `$0.00237938`.
   Provider `/models` endpoints emitted no quota headers, and one sample cannot establish monthly
   availability, latency tails, quotas or decision quality. Every paid LLM caller now shares a
   durable provider-wide spend ledger with pre-call reservation, and X uses its own durable
   monthly ledger. Continuous paid testing still needs an approved cadence, quality protocol and
   stop conditions within those enforced limits.
5. **Operations still need elapsed and off-host evidence.** A clean local backup/restore drill
   passed 12 migrations and 18 critical tables, and the read-only services recovered their
   persisted state. This does not prove long-duration or off-host recovery. Production still
   requires managed KMS/Vault signing, encrypted off-host backup scheduling, host hardening and
   an independently reviewed recovery drill.
6. **Backtests are not venue qualification or alpha.** The frozen candidate loses money in the untouched
   July holdout, trails its benchmark, has too few OOS trades, and lacks historical funding
   evidence. Every existing sleeve is `REJECTED`; the deterministic fill model also needs real
   EVEDEX TCA calibration before results can inform any future PAPER risk limits.
7. **Model migration still needs live shadow evaluation.** The four API routes now pass one exact
   structured-output probe, but that does not prove that Luna/Terra/Flash preserve decision
   quality, latency tails and token profiles on production distributions.
8. **Advanced position management is outside v1.** Break-even stop moves, trailing, multi-TP and
   protective-order updates are intentionally absent; v1 supports exactly one SL, one TP and one
   timeout.

## Readiness rule

Do not interpret `TECHNICAL_PAPER_READY=true` as permission to publish a canary, run a rejected
strategy or enable LIVE. The permitted order is: 24 hours read-only, one manually armed bounded
DEV canary session, completion of the five-symbol lifecycle matrix, then a seven-day soak.
`PAPER_QUALIFIED` remains false until that evidence is reviewed. Automatic PAPER additionally
requires a new strategy revision to pass the offline promotion gate. LIVE requires a later,
separate managed-secret and real-funds review; it cannot be enabled by a legacy boolean.
