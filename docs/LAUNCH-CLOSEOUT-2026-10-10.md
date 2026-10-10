# Controlled-launch engineering continuation — 2026-10-10

## Scope and result

The owner prioritizes completion toward a controlled launch before further
profit optimization. This continuation fixes release-source verification and
adds the missing local alert-acknowledgement mechanism. Neither change grants
trading authority. UI/UX and strategy tuning remain deferred; Trial 15, V2,
V4/V5, their ledgers/evaluators and unfinished adaptive research are untouched.

The [current manifest](../config/current-release.json) records Deploy
`93b9d4a448d067ab31cf1c8058ec786975e5ee0f`; the other component pins are unchanged.
Meta deliberately uses `SELF`. All four readiness fields remain false, policy
is `REJECT_ALL`, and both trading/simulator authorities are `NONE`.

## Delivered changes

### Release-source projection

Previously, release projection did not bind Text Scouts and Macro runtime
identities to the composition gate. A regression changing those two runtime
revisions reproduced the omission: the old validator returned no errors.

Deploy now validates the exact original eight-component current-release gate
and the separate nine-component Text/Macro composition gate. Shared pins cannot
override each other; repositories, revisions, schema, classification, readiness
types and default rejection are checked. Existing gate scopes are not expanded
and frozen locks are not rewritten.

Meta now checks all nine runtime services, including Quant, and all three
runtime dependencies against its manifest, as well as the current, SIM and
composition gate sets. Its functional fixture derives identities from the meta
manifest and works without a sibling Deploy checkout. The actual installed
composition fixture already verifies noneditable PEP 610 repository/commit
identities; no duplicate installation verifier was introduced.

Signed implementation commits:

- Deploy `44babf40364c6550ae318fc110fb313c52a6dc20`.
- Meta `a774e3a0976c7e2de93026976881a411ca2b30cb`.

### Telegram local operator attestation

Deploy `93b9d4a448d067ab31cf1c8058ec786975e5ee0f` adds `acknowledge` and `verify-ack`
to [the existing delivery tool](https://github.com/Kairos-cryptoAI/kairos-deploy/blob/93b9d4a448d067ab31cf1c8058ec786975e5ee0f/scripts/alert_delivery.py).
It requires the explicit `OWNER_SAW_QUALIFICATION_MESSAGE` statement, a pinned
original journal SHA-256 and the exact accepted message ID. It validates the
bounded protected test journal, all four successful stages, recipient/message
identity, stable source fingerprint, typed flags/counters and UTC time order.

The acknowledgement is a separate exclusive, fsynced receipt. It cannot
overwrite an existing or partial receipt, mutate the send journal, read a bot
token, send again or call Telegram. Readback revalidates the original journal;
a missing/changed journal, unknown dispatch outcome or future terminal time is
rejected. Historical source hashes may differ from the new tool, but must be
valid and identical across the original journal.

This is explicitly `LOCAL_OPERATOR_ATTESTATION`, not authenticated Telegram
user identity or proof of delivery. `telegram_user_authenticated`,
`operationally_qualified` and `trading_authority` remain false. No real owner
acknowledgement or message delivery was recorded in this continuation.

## Local verification

- Final Deploy suite on Windows Python 3.11.15 and 3.14: **477 tests in each**,
  **473 passed and 4 explicit skips**, zero failures. These are engineering
  fixtures, not a real database recovery, venue or alert-delivery qualification.
- Meta static/functional tests pass in PowerShell 7 and Windows PowerShell 5.1.
  The new projection also passes against the actual declared Deploy JSON files.
- Changed-file formatting/source checks and `git diff --check` pass. All three
  implementation commits carry the configured trusted GPG signature.
- Hosted acceptance is recorded separately after the exact-source CI runs;
  local tests alone do not stand in for green GitHub/native integration gates.

No primary database mutation, consumer start, PAPER/LIVE lifecycle, venue order,
provider call, Telegram call, secret-value read or backup upload occurred.
Existing disposable/shadow state and historical failed attempts were preserved.

## Remaining launch admissions, in dependency order

| Admission | Actual remaining work |
| --- | --- |
| Clean source release | Preserve and independently finish or explicitly relocate the existing unfinished adaptive drafts before the full clean-checkout gate; source projection alone does not accept them. |
| Runtime recovery | Admit a fresh official backup with its own ownership, before/after provenance and complete manifest; then accept the complete atomic isolated clone/schema/outbox/lease proof. Primary migration, lease/cursor changes and consumer starts remain separate guarded steps. |
| Alert channel | Rotate the previously exposed token of the existing single bot, establish its accessible test/final groups, then perform the bounded delivery/owner acknowledgement and restart/host-loss checks. Existing `CHAT_NOT_FOUND`/unknown-send evidence cannot be upgraded by the new attestation code. |
| Host and backup | Owner has no separate remote storage yet and plans a later host deployment. Select and qualify that host/custody and a separate encrypted backup destination, retention/RPO/RTO and actual off-host database restore. A backup on the application host alone is not off-host resilience. |
| EVEDEX DEV | Prove dedicated DEV pairing and five-symbol GET-only quality, then separately authorize the bounded DEV canary and seven-day soak/TCA. Keys being available is not venue qualification. |
| Adaptive economic admission | Fix one candidate/evaluator and complete its own sealed 365 future days and 500 natural closes, crash/risk/profit-factor gates and matched controls. Short seen-data tests and Trial 15 credit cannot replace this. |
| Production security and controlled LIVE | Review security, managed custody, DEV/PROD separation, real monitoring/restore and production limits; require owner dollar-cap/day-stop-loss and separate manual arming before any real canary. Ramp remains manually approved. |

The [October 5 recovery receipt](RECOVERY-2026-10-05.md) remains authoritative:
the preserved archive restores diagnostically, but its failed official workflow
did not produce a manifest. The official backup requires 47 native calls; the
audited additive transport candidate is still unarmed. The old failed lease,
partial attempts, source fingerprints and retained artifacts are not adopted,
retried, reset or deleted. This continuation does not waive those boundaries.

The [market-only model comparison](MARKET-REVIEW-2026-10-10.md) is a bounded
historical diagnostic, not complete-system alpha. Deferring profit optimization
does not waive minimum economic/risk evidence needed before real money.

```text
TECHNICAL_PAPER_READY=false
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
TRADING_AUTHORITY=NONE
```
