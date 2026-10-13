# EVEDEX: finite non-trading closeout — 2026-10-13

This additive checkpoint follows the
[earlier three-pair public diagnostic](EVEDEX-DEMO-TECHNICAL-SCOPE-2026-10-13.md).
It closes engineering and a bounded Demo GET-only account sample, not trading,
five-symbol liquidity, signing authority, PAPER, alpha or LIVE qualification.
The [signed factual receipt](receipts/evedex-nontrading-closeout-20261013.json)
binds source revisions and protected evidence without publishing account IDs,
wallet addresses, credentials, private responses or financial amounts.

## Closed independently

1. **SDK session replacement.** Failed authentication/preflight/listen now
   invalidates cached accounts and closes the candidate. Old/failed session
   callbacks are fenced by generation. Previously accepted, undrained events
   survive reauthentication; post-admission live events enter the normal queue.
   The tentative buffer is bounded at 10,000; overflow fails closed instead of
   hiding an event gap. Close invalidates accounts, including an in-flight listen.
   Read refresh retry remains at most one; mutations are never retried.
   Production still uses official SDK 1.2.11, the fixed DEV profile and all five
   required instruments. Only trusted test code can inject the fake container.

2. **Demo response contracts and empty-state agreement.** The pure parser has
   no transport, credential reader, database or trade method. It validates the
   official DTO shapes: notably `GET /api/order/opened` returns `OpenedOrder[]`,
   not paginated `OrderList`. Wallet currency may be a public coin ID. Only an
   exact match with the unique catalog entry whose symbol is `USDT`, or the
   literal symbol without a catalog contradiction, is accepted. No `USD` alias
   is invented. Counts, missing fields, non-finite numbers, inconsistent pages,
   ambiguous coins and nonempty components cannot produce an accepted empty state.

3. **Fresh existing Demo account sample.** Between **18:37:05–18:37:24 UTC**,
   one signed operational helper made exactly **7 GET attempts, all HTTP 200**:
   identity, available balance, positions, opened orders, TP/SL, wallet balance
   and the public coin catalog. Identity matches the previously accepted
   browser/API binding. Positions, opened orders, TP/SL and reservations agree
   as empty. Wallet test USDT is positive and matches the unique public coin ID;
   funding/margin and available balance are zero. This resolves the earlier
   wallet-format rejection without overwriting that failed receipt. No balance
   amount is published. No transfer, faucet request, wallet authentication
   signature or order was attempted. GET access does not prove order permissions
   or the signing credential. These serial reads are not an atomic/24-hour proof.

4. **HTTP dependency exclusion.** Execution now enforces and locks
   `multidict>=6.9.1,<7`, with 6.9.1 installed in both isolated test environments.
   [The upstream advisory](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925)
   identifies a reference leak in versions 6.7.0–6.9.0 and the 6.9.1 fix. Three
   small offline tests guard the version floor and operand-reference cleanup.
   Optional CCXT moves from 4.5.85 to 4.5.87 because the previous release pins
   vulnerable multidict 6.7.1; no CCXT session is started. GitHub alert 16 became
   `fixed` at 18:40:23 UTC. Running runtime environments/containers were not changed.

## Verification and delivery

- Execution Windows Python 3.11.15 and 3.14.7: **582 passed on each**, with 45
  database integration tests explicitly deselected locally. Those are not counted
  as local integration passes. Exact Execution source passed hosted
  [CI](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/38448493296)
  including its isolated journal integration, all adapters and Node dependency audit,
  and [CodeQL](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/38448493673).
- Sidecar Node 22.22.0: **25 passed** on Windows and in an existing image with
  network disabled, read-only source, resource limits and no secrets/runtime mount.
  The real SDK authenticated entry point was never started.
- Ops: **215 passed on each Windows Python version**, including 13 new pure
  parser tests. The one-shot private GET transport has six additional offline
  tests for reservations, no retries, no key on public requests, bounded response
  size, deadline and redirect/foreign-path rejection.
- Deploy stdlib suite: **980 run, eight skipped, no errors** on Python 3.11.
  Changed locks, source projections and Compose validators pass locally. Earlier
  failures from stale Execution environments and a third-party `tests` package
  collision were retained; fresh locked/stdlib environments resolved them without
  changing runtime or unrelated source. Ruff/format, mypy, Bandit and Meta static
  checks pass. The parser source passed all three exact-source hosted gates.

GPG-signed `main` revisions are `eebfd35` (parser), `3ad03d8` (SDK admission),
`f8dd4cd` (dependency exclusion) and `b311b83` (current deployment projections).
Both affected gate locks were regenerated, not hand-patched. Meta's current
release manifest records those current sources while all readiness remains false.
Earlier Docker/receipt evidence is not relabeled for this new source identity;
exact-SHA hosted Deploy/Meta checks must finish before final delivery acceptance.
No local full Compose build/up, runtime migration, consumer start, queue repair,
paid model call or research/evaluator/ledger change is part of this work.
The pre-existing 43-path adaptive WIP and Execution's orphan test directory remain.
No full clean-checkout current-release gate is claimed while that WIP exists.

## Support response and unchanged boundary

The later visibly inspected reply in official ticket **1013-20**, from Daniel,
confirms only three pairs and one Demo account at present. No alternate active
BTC/ETH/SOL/BNB/XRP no-real-funds route was supplied. Protected reply/screenshot
evidence is separately signed. The first screenshot captured older conversation
context; it is retained but is not the final proof. The refreshed second capture
shows the actual latest response. No further message or attachment was sent.

This reply is a statement about current Demo support, not proof that every
possible DEV environment is nonexistent. Still, the available three-pair Demo
cannot pass the unchanged five-instrument gate. 1000PEPE is not substituted for
SOL/BNB/XRP. No mainnet funding or manufactured liquidity is proposed.

| Remaining item | Current boundary |
| --- | --- |
| Official active five-symbol test route | Not supplied; current Demo is limited to three pairs. |
| Dedicated signing/key permission acceptance | Not demonstrated by GET access; wallet signature count remains zero. |
| 24-hour five-symbol availability/basis/TCA window | Not started or accepted; three synthetic Demo prices cannot substitute. |
| DEV canary and seven-day soak | Not started; the owner currently prohibits trading. |
| PAPER/ALPHA/LIVE | All false, with `STRATEGY_POLICY=REJECT_ALL`. |

Test funds already exist on the Demo wallet, but a later internal transfer would
be a separate owner handoff; none is performed here. This finite closeout does
not arm anything or weaken the release/research/risk/venue gates.
