# Concept corrections: engineering receipt

Date: 2026-10-06 Europe/Moscow. Classification: ENGINEERING_ONLY.
This receipt records concept/code corrections, not a trading qualification.
The current source authority is [current-release.json](../config/current-release.json).
All readiness remains false; strategy policy remains `REJECT_ALL`.

## Completed corrections

1. **Living concept and truthful scope.** [CURRENT_CONCEPT.md](CURRENT_CONCEPT.md),
   README, architecture, budget and ADR 10 now distinguish current implementation
   from frozen plans, historical receipts, accepted fixtures and running services.
   Current OpenAI-only defaults are not advertised as proven best models. Existing
   shared spend/reservations and the $12/$1/$2 ceilings are not reset.
2. **Explicit strategy evaluations.** The additive runtime adapter emits
   `StrategyEvaluationV1`: intent, valid no-intent, warmup, not-scheduled, disabled,
   unavailable and error are different observations. Prepared receipt/intent bytes
   survive retries; recovered batches verify exact source/config/revision links.
   All eleven existing frozen generator fingerprints remain unchanged. Unsupported
   adapters and quiet/disabled engines do not become the new adaptive candidate.
3. **Causal review context.** Runtime review requires immutable `DecisionContextV1`
   with exact intent/route identity and separate source event, trusted local receipt
   and capture times. Required missing, late, stale, conflicting or wrong-symbol
   inputs cause `DEFER` before a model call. The supplied bars are the exact bounded
   intent-declared tail, not an invented full history/warmup proof. Optional unknown
   inputs stay explicitly unavailable. Context is published before review; completed
   retries preserve the original cut. Legacy context-free review is explicitly an
   engineering compatibility API, never the normal service fallback.
4. **Versioned regime/capital policy.** Disabled-by-default Macro/Risk handlers
   bind exact strategy/code/config, detector, policy/source set, intent and account
   identities. BULL/RANGE/BEAR/CRASH direction capability is explicit; UNCERTAIN has
   no entry capability, and legacy CHOP is not relabelled RANGE. Capital weights
   are caps, not trading permission. The 0.25% per-trade and 1% open-risk ceilings,
   all approval/account/venue/operator checks and technical-canary limits remain.
5. **Model/provider identity drift.** Risk recognizes the implemented current routes
   `gpt-6-luna` and `gpt-6.1-sol`. Legacy, unknown or wrong-provider successes cannot
   clear a current aggregate provider outage. A new regression exercises the real
   health consumer, failure/degradation/recovery and ACK behavior. Text Scouts
   now receives the OpenAI + X file bindings its real defaults require, rather
   than only DeepSeek. Rendered base/LIVE validation requires the exact active
   seven-secret inventory; dormant legacy provisioning compatibility is separate.
6. **Reproducible integration.** Runtime/PAPER projections, installed composition
   and two current engineering gate locks use the same published component SHAs.
   Fresh `20261006-r5` gate identities replace the current r4 profiles without
   rewriting their historical receipts or `tests/release_gate`. Review and Risk
   fixtures now share the same Macro payload rather than contradictory snapshots
   under one ID. Stale required Macro yields zero provider calls.
7. **Packaging and build truth.** Risk sdist excludes local `.venv*` directories;
   archives were checked by names, without reading secrets or removing environments.
   The previously accepted bounded Compose fixture is correctly recorded as
   synthetic-only, with forced-disconnect cancellation rather than graceful
   production-client cancellation proof. No repeat build was needed to update docs.

## Local evidence on published component pins

Every component below passed locked Python 3.11 lint, format, mypy, Bandit,
offline unit tests and wheel/sdist build. Separate external environments were
used; existing user `.venv` directories were not replaced.

| component | passed | skipped / excluded |
| --- | ---: | --- |
| Core | 321 | 2 Redis tests without a local server |
| Persistence | 504 | 1 skipped; 34 native integration tests excluded |
| LLM | 272 | 6 native/provider fixtures not selected |
| Quant | 270 | none |
| Strategy | 438 | none; source-level Python 3.14 regression also 438 PASS |
| Text | 91 | none |
| Router | 55 | none |
| Aggregator | 83 | none |
| Macro | 92 | 1 DB drill not selected |
| Risk | 275 | none |
| Execution | 579 | 45 native/exchange fixtures not selected |

These are 2,980 component passes, not 2,980 live trades or a native integration
qualification. Deploy static tests additionally ran 457 cases: 454 passed and
three skipped.
The installed non-editable context composition passed 28/28; the exact current
REJECT_ALL fixture passed 7/7. An initial invocation without its explicit opt-in
failed closed as designed; the guard was retained and the correct fixture opt-in
was supplied for the accepted installed run.

## Source-bound hosted integration evidence

The signed Deploy source is `1630fd1d5e7863d8a85140225fe52bc052201347`.
The following gates passed on that exact source and its published component pins:

- [Installed native composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37376202944):
  real disposable PG16/Redis, verified non-editable consumers, fresh controlled
  schema, actual service handlers and committed-ACK-loss replay. The independent
  result check accepted exactly one native test and zero skips; cleanup passed.
  Provider results are injected zero-spend fixtures, not economic/live evidence.
- [Current-source REJECT_ALL gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37376203006):
  Windows/Linux policy tests and the isolated Docker bar-to-refusal proof passed.
- [Full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37376202913):
  Windows/Linux isolation tests and the actual bounded PostgreSQL/controller
  simulator proof passed. It is engineering evidence with the explicitly legacy
  review compatibility fixture, not qualification of the new mandatory context
  runtime, PAPER venue, strategy profitability or LIVE.
- Five real Compose renders using public examples passed the security validators:
  base, fail-closed LIVE overlay, PAPER static topology, current gate and SIM.
  Rendering the PAPER/LIVE profiles did not launch either trading contour.

The separate local Windows native launcher did **not** execute the native test.
Its first preflight refused a bounded inventory check before creating resources.
A subsequent explicitly reviewed preparation stopped on the launcher's handling
of an absent pre-start Docker health field. No DB/service was started; the
refusal/failure logs are retained, not reclassified as successful evidence.
This does not replace the independently successful hosted native gate above.
Focused cleanup subsequently verified the exact UUID-owned, never-started
container and removed only that descriptor, without force or volume removal.
All 33 pre-existing container descriptors/states remained unchanged. The original
failure logs and the separate cleanup proof remain under
`D:\Kairos\runtime\concept-corrections-20261005`; cleanup is not a native test pass.

## CI status and remaining release checks

All eleven changed components' test CI workflows and Deploy's main CI passed
on the exact published revisions in the current manifest. Individual jobs,
not just workflow titles, were checked. Some initial component jobs acquired no
hosted runner; one failed-job-only retry on the unchanged SHA completed those
test matrices. No application code or source identity was changed for a retry.

| source | accepted test CI run |
| --- | --- |
| Core | [37371496708](https://github.com/Kairos-cryptoAI/kairos-core/actions/runs/37371496708) |
| Persistence | [37371811415](https://github.com/Kairos-cryptoAI/kairos-persistence/actions/runs/37371811415) |
| Execution | [37372475682](https://github.com/Kairos-cryptoAI/kairos-execution-engine/actions/runs/37372475682) |
| LLM | [37372867573](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37372867573) |
| Strategy | [37372720977](https://github.com/Kairos-cryptoAI/kairos-strategy-engine/actions/runs/37372720977) |
| Router | [37372722483](https://github.com/Kairos-cryptoAI/kairos-router/actions/runs/37372722483) |
| Quant | [37372478023](https://github.com/Kairos-cryptoAI/kairos-quant-scouts/actions/runs/37372478023) |
| Text | [37373166029](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/37373166029) |
| Aggregator | [37373324186](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/37373324186) |
| Macro | [37373658581](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/37373658581) |
| Risk | [37374223663](https://github.com/Kairos-cryptoAI/kairos-risk-manager/actions/runs/37374223663) |
| Deploy | [37376202951](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37376202951) |

The separate security/default-setup matrix is **not fully green**. Core,
Persistence, Execution, Router, Quant and Text CodeQL workflows and LLM's
dependency-graph workflow still show failures. Confirmed hosted allocation
annotations report `The job was not acquired by Runner of type hosted even after
multiple attempts`; a workflow with no executed steps is not a security pass.
GitHub refused the attempted rerun of Core's CodeQL and LLM's dependency-graph
default-setup runs. Security workflows were not disabled or reconfigured, and no
empty source commits were made to manufacture green checks. The independent
successful test/integration gates do not override these incomplete checks.

The local current-release guard checks trusted signatures, source/pin identity,
tracked cleanliness, action pins and tracked credential-like patterns. It uses
`--untracked-files=no`: even a successful run cannot certify absence of untracked
local artifacts. Two unrelated untracked pytest-artifact directories remain
preserved in Quant and Execution and are disclosed separately. None of these
engineering checks grants trading permission.

## Deliberately not claimed or enabled

- No selected/frozen new adaptive strategy, deterministic detector publisher,
  economic evaluator or new 365-day blind enrollment is created by these types.
- No durable production point-in-time history/context archive or exactly-once
  paid model dispatch after an uncommitted crash is qualified. The old context-free
  corpus does not qualify the new mandatory context service.
- Durable capital-basis restore, full analytical runtime topology and reviewed
  non-canary Execution admission remain separate integration work.
- No primary PostgreSQL migration/recovery, outbox dispatch, lease/cursor reset,
  consumer start, external exchange/provider call, paid API call or real order.
- Trial 15, V4/V5 plans/ledgers/evaluators, old receipts and research PnL remain
  untouched. Existing unrelated untracked pytest-artifact directories in Quant
  and Execution remain preserved, so no claim of fourteen clean local worktrees
  is made.
- No UI/UX implementation, production key custody or premature LIVE permission.

The next useful work is the explicitly missing selected detector/strategy and
matched economic evaluation, durable causal/basis recovery and reviewed full
runtime integration, followed by independent strategy, provider, DEV and PROD
qualification. [CURRENT_CONCEPT.md](CURRENT_CONCEPT.md) remains the living scope;
this engineering receipt does not replace any frozen research plan/evaluator.
