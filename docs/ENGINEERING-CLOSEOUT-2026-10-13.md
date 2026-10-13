# Kairos: engineering closeout, 2026-10-13

This receipt separates implemented engineering, native acceptance, offline fixtures,
and research/trading qualification. It is not a PAPER, alpha, or LIVE approval.

## Boundaries

- Only the already authorized separate non-trading epoch
  `69893dc7b7c647f49967387e7efca9fb` was recovered.
- The legacy primary database and its Redis/queue were not modified or started.
- No strategy, PAPER trading service, authenticated EVEDEX session, order, canary,
  funding action, or paid OpenAI/DeepSeek/X request was started.
- Trial 15 and quarter-hour V2/V4/V5 identities, plans, ledgers, evaluators, and
  blind performance evidence were not rewritten or credited to another campaign.
- Readiness remains `TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`,
  `ALPHA_READY=false`, `LIVE_READY=false`, and `STRATEGY_POLICY=REJECT_ALL`.

## Six work items: evidence and remaining acceptance

| Item | Completed engineering/native evidence | Not established by this work |
| --- | --- | --- |
| Non-trading runtime | R7 recovery accepted; fresh before/after backups restored and checked in isolated clones; five-symbol progress and graceful stop/restart proved; new guarded boot binding and task installed. | Long-duration uptime, a new physical host/reboot qualification, trading or production readiness. |
| Current Text / review qualification | OpenAI-only provider-bound Text qualification and current full `DecisionContext` Aggregator V2 fixtures; stale/future/missing/conflicting/injection cases; 97 tests per repository and green CI. | Paid provider/model quality, profitability, or eligibility of a new blind strategy. |
| Matched A/B campaign bridge | Separate offline adapter with causal capture/cutoff, missing/late/unknown denominators, provider-call reservation, no-resend restart behavior, and 12 passing tests. | A current native campaign with real provider/Persistence/Risk bindings and accepted immutable campaign identity. The old campaign is not silently rebased. |
| Public venue observer | Standalone bounded observer independent of PAPER; pinned measurement source, five-symbol denominator, reserve-before-wire ledger, and one native public smoke slot. | DEV account/auth pairing, continuous 24-hour venue qualification, canary or seven-day soak. |
| Technical notifications | Typed source feed and a signed send-once journal with terminal UNKNOWN outcomes; business signals remain muted. | R7 operational task and native delivery acceptance are recorded below only when actually verified. |
| Local encrypted backup | Native Restic snapshot of the two accepted dump files and receipt; full authenticated data check, wrong-password rejection, and exact byte/hash restoration. | Off-host durability, a remotely stored password/recovery key, or a remote restore. No destination was supplied. |

## Native R7 recovery

Accepted work:
`D:/Kairos/runtime/runtime-incident-20261013/read-recovery-r7-cb1bc3984d8440aa965af5b928d2b4fa`.

- Accepted receipt SHA-256:
  `03b10208edd5d5d7957ceaf2d38a6d73b7acbef03bfd4f2a87e1fa8ef88cacb0`;
  detached GPG signature retained next to the receipt.
- Accepted runtime source: `98016d0f28fb175ba3a49ad328c2779c000e27d3`.
- Before backup: 44,250,966 bytes,
  `f9b9df64f3071dcf599b3fd2624b1e6ef368fcb6285a881959bbb20320b56e3a`.
- After backup: 44,277,022 bytes,
  `673d3a098817d1d9478b45f899d3095a24e065b2e2bc1106d8ec15237d45ae84`.
- Both fresh SQL restores checked the full 32-table inventory and database
  integrity in the isolated `transport08` clone, not the legacy primary.
- The earlier reviewed recovery completed exactly ten already-published inbox
  messages: +10 inbox completions, **zero** new publications/stream entries/
  publication receipts, preserved history/outbox/sequences. The final continuation
  did not execute that drain again.
- R7 container: `c08f5b667a84febb2dc1639857b44a52208ea29f9836e14c11685d89ccd55ae0`;
  `kairos-epoch-69893dc7b7c6-serve-r7`. Acceptance observed `RUNNING_NONTRADING`,
  fresh five-symbol watermarks, no pending/unresolved/uncompleted queue work,
  and a proved graceful restart. Subsequent bounded checks observed continued
  progress, not merely a still-alive process.
- Historical R6 root cause is **not** proven. Its failure/status, failed R7
  attempts, cold byte copies, and the unstarted verification helper were retained.
- Guarded boot binding SHA-256:
  `ff7c57ea4c56eb32e50189de4d0d6dea2b08e55af15fccee57327b20aacc2879`.
  Native boot admission returned `ALREADY_RUNNING_NONTRADING` without starting a
  duplicate. Receipt SHA-256:
  `60f02b69041b0b0cd429e5f375e3c7865b822324d8aac5ccb756320636f213c9`.
- `Kairos-NonTradingEpoch-69893dc7b7c6-Boot-R7` is registered with logon-only,
  delayed, Limited, IgnoreNew, no automatic restart semantics. The superseded R6
  boot task is disabled, not deleted. A host reboot was not performed here.

## Native local Restic acceptance

- Pack source: signed Deploy `9f4410bedb48d8d71d03965cc3e8318b9e2e8cbd`.
- Result: `PASS_LOCAL_ENCRYPTED_R7_PACK_AND_RESTORE`.
- Snapshot: `8e5e192386486bf6d76c5cfd8eb0f6babf1930b03c296bcfb04fe0f8f7eca21e`.
- Pack receipt SHA-256:
  `c6fb0741bb03d98dd22144a8ae19d3bdb0366db41e810c9c9348fed1c98e2f13`;
  detached GPG signature retained. All three restored files matched their exact
  original SHA-256. `check --read-data` and native wrong-password rejection passed.
- Only the two accepted dump files and sanitized receipt entered the snapshot;
  no exchange/provider keys, live connection configuration, or raw queue was added.
- Repository/password are private local artifacts. No password value was printed;
  no network request or upload occurred. This protects against accidental local
  corruption, **not loss of this computer/disk**.
- The failed long-path GPG verification workspace was preserved. A separate
  create-only short public-only import home corrected the Windows GPG path defect;
  signature rejection and the no-retry repository claim remain intact.

## Public venue smoke: limitations are part of the result

Smoke directory:
`D:/Kairos/runtime/evedex-venue-observer-smoke/run-e128912e-6206-4559-8778-d65e0e1a496c`.
Exactly one slot, ten reserved/attempted/completed public GETs, 53.03 seconds,
no authentication, orders, database, Redis, automatic retry, or readiness change.

Only BTC and ETH produced a usable measured pair. SOL/BNB/XRP remained in the
five-symbol denominator with no usable pair; they were not dropped to inflate
availability. Observed BTC book age/skew was 6,209 ms, and ETH skew 3,041 ms.
The retained public EVEDEX replies for SOL/BNB/XRP contained empty `asks` and
`bids` arrays. No quote was invented or substituted for those missing books.
These sparse, client/network-sensitive observations do not pass the intended
5-second age / 2-second skew requirements or establish any 24-hour percentile.
The smoke latch is separate from the future 24-hour observer and was retained.

## Source/CI evidence and open gates

- Text: `c3804a9e50f341cf35322fabb6967ccc4d8a95a5`; CI `38384462521` and
  CodeQL `38384462405` succeeded.
- Aggregator: `c45e3104c07503e46b26ea6d0a341d8ba7153a44`; CI `38384823249`
  and CodeQL `38384823718` succeeded.
- Deploy: `9f4410bedb48d8d71d03965cc3e8318b9e2e8cbd`; 980 tests passed
  on each of Python 3.11 and 3.14 (eight deliberate skips per suite). CI
  `38399169213`, composition `38399169324`, and CodeQL `38399169096` succeeded.
- Current manifest source projection, runtime/PAPER lock projection, current-source
  `REJECT_ALL` policy, and full-path simulator deployment validators passed.
  Full-path and composition engineering gates do not arm a trading process.
- All 14 current HEADs are on main, match their local `origin/main`, and have the
  required GPG signer. This does **not** mean every checkout is clean: 43 unrelated
  adaptive WIP paths and old untracked test artifacts in Execution/Quant were
  preserved. The strict whole-workspace clean release gate is not accepted.

Remaining qualification is explicit: a current native A/B factory and durable
Risk/provider budget coordination; causal market/news evidence; owner-approved
sealed adaptive strategy/evaluator followed by its own 365 days and 500 naturally
closed simulated trades; DEV identity and venue/account qualification; off-host
storage/recovery; production secret backend, security acceptance, and manually
specified LIVE capital/stop-loss limits. No elapsed baseline day or synthetic
fixture is substituted for these gates.
