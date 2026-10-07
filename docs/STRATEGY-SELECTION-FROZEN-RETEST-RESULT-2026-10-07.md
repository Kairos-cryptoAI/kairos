# Frozen retest result: not selected as the technical baseline

The [single predeclared hypothesis](STRATEGY-SELECTION-FROZEN-RETEST-PROTOCOL-2026-10-07.md)
was implemented and tested as `frozen_breakout_retest_v1`, separately from every
native/compact/frozen trading line. The initial source/protocol commit is
GPG-signed `2bcd5f0f8b8b8d1d7587d82d97fdf20c60e520c5`; its Windows/Linux
Python 3.11/3.14 CI, meta validation and CodeQL are green. Local non-editable
wheels passed 756 tests on each Python version, with two Windows symlink-rights
skips. Dependencies and their locks/revisions were not changed.

## Actual one-time census

`D:\Kairos\runtime\frozen-retest-census-20261007-a` completed once in
40.015 seconds (separately observed child-process elapsed 41.07 seconds, with an
external 300-second kill cap). There was no retry. The seven original
[published artifacts](../development/adaptive_replay/evidence/frozen-retest-2026-10-07/result.json)
are byte-bound and preserve before/after source equality. The lossless 149,694-byte
gzip contains the entire canonical decision tape, not selected successful rows.
Independent read-only recount found no checksum, ordering, roster or counter
discrepancy; it did not rerun the generator or simulate economics.

| Observation | Actual count |
| --- | ---: |
| Complete 5m symbol slots, two five-day episodes × five assets | 14,400 |
| Armed breakouts | 122 |
| First retests recorded | 50 |
| Distinct structural reclaims, consumed before admission | 23 |
| Reclaims rejected: net reward/risk below fixed 1.25 | 13 |
| Reclaims rejected: costs exceed half stop distance | 5 |
| Reclaims rejected: known target no longer beyond reclaim price | 5 |
| Candidates remaining after fixed base 20 bps planning hurdle | 0 |

All ten UTC-day counters (fifty symbol-days) retain zero candidates. The fixed
33 bps stress scenario is retained, but with no base-eligible candidates neither
scenario has reference/arrival executions to compare. This is **not** a zero
return, a loss measurement, observed fill performance, or a model A/B result.

The old-channel reset restriction also kept 12,165 slots (84.48%) waiting for
reset. That is a real structural opportunity restriction, not just a paid-model
latency issue: a continuing trend cannot repeatedly reuse the same frozen event.
Twenty quiet pilot cells were insufficient to see this; the complete census
makes the denominator and refusal causes explicit.

## Decision and safe continuation

Do **not** select this initial retest version as Kairos's principal technical
candidate producer, integrate it into production/compact policy, or spend a
review-only model pilot on its empty candidate set. The known target and original
stop leave insufficient declared cost/geometry headroom in these already seen
windows. Do not improve its displayed result by extending targets, tightening
stops, lowering cost/risk hurdles, shortening reset, removing assets/days or
re-running variants. Source and policy stay exactly as preregistered evidence.

This rejects the current implementation as the intended technical baseline,
not all retest concepts and not every independently generated LLM proposal.
Neither it nor the earlier native controls is a qualified full-system winner.
The compact complex remains an unchanged comparison control; any materially
different hypothesis needs its own predeclared identity and evidence. For the
eventual full-system historical test, accepted causal NEWS/MACRO archives,
source/budget admission and fresh human confirmation are still required.
Models cannot rescue entry whose fixed barriers fail Risk Manager geometry.

No provider calls or new spending occurred; no PnL/exit replay or blind credit
was computed. Trial 15, V4/V5, old source attempts, ledgers, native TTLs, release
dependencies and evaluator remain untouched. No runtime recovery, consumers,
venue/PAPER/canary/LIVE services or keys were used. Readiness remains false and
`STRATEGY_POLICY=REJECT_ALL`.

Protocol canonical SHA256:
`3eb06d2a3397b19ba17a8ad54dfd41a39c324921a3ab319962e9b00b101d12e4`.
Complete uncompressed decision-tape SHA256:
`5341f26d0c7147df08b65cac0896395eb0b33dcdca698324d2f84326743a2c7a`.
