# Separate market-only retrospective comparison

This is a research harness, **not** a route around NEWS/MACRO, historical pilot,
campaign, runtime or LIVE gates. Never call its real worker from CI or fixtures.
The [completed report](../../docs/MARKET-REVIEW-2026-10-10.md) records negative and
zero-trade results as well as limitations. All qualification flags remain false.

`run_comparison.py prepare` validates the immutable prior native tape and archive
checksums, reproduces **every candidate**, masks date/asset/absolute prices and
seals the request roster before observations. `model_worker.py` makes one native
budgeted OpenAI request per candidate in the predeclared immutable image. It
requires the **existing** adopted cumulative shadow budget (not primary runtime),
protected file-mounted credentials, a create-only run marker and a local $1 cap.
It never migrates, adopts/reset budgets, releases ambiguous costs or retries.

`run_comparison.py finish` validates exact committed review coverage and reruns
strategy-only, latency-plus-cost control and market-only review with unchanged
native intents/risk/cost scenarios. Original clocks, TTL, stop and target remain
unchanged. API costs are retained for ALLOW/VETO/DEFER. Unknown costs prohibit a
complete economics result. The old full NEWS/MACRO pilot remains separate.

Use the locked `development/adaptive_replay` environment for offline checks:

```powershell
python -m pytest --rootdir=. --confcutdir=. --import-mode=importlib . -q -W error
ruff check .
ruff format --check .
```

Run these commands with this folder as the working directory. They read public
saved receipts; **no providers, DB connections or trading mutations** occur.
The exact pre-format sources used for the paid experiment are retained as byte-
identical `.py.txt` snapshots under `evidence/2026-10-10/sealed-sources` and hashed
by `result.json`. Current source differs only by formatter/import/comment cleanup;
the saved experiment identity is not rewritten. Runtime source ZIPs, full prior
native tapes and cache remain local and immutable, not duplicated into Git.

## Current-context admission diagnostic — October 15

`tools/check_current_context.py` is a separate **offline refusal diagnostic**, not
a rerun or relabeling of the completed paid experiment. It reuses its original
validated real candles and complete slot roster, regenerates all 12 candidates
with the current unchanged adaptive strategy and strict adapter, then invokes
the actual candidate Router/current-context review handlers. No market snapshot,
NEWS, Macro or book is fabricated. Required missing context must produce
deterministic DEFER before a forbidden gateway can be invoked. Risk, SIM execution,
budget database and provider clients are never constructed. Old paid responses are
coverage-checked but not supplied to this review.

The actual [result](evidence/2026-10-15-context-admission/result.json) is
`REAL_MARKET_INPUT_ADMISSION_BLOCKED_MISSING_CONTEXT`, with 12 DEFER and zero new
calls. Strategy observation and source-receive times are explicitly projected
replay clocks, not historical observation receipts. CLI exit 3 means this expected
blocked state; exit 2 means the diagnostic itself failed. There is no success
code for a full-system/model/economic test. All output is create-only.

Run using a separately pinned environment with the current eight-component
source set plus the existing Backtest/archive loader and adaptive replay package:

```text
python -I tools/check_current_context.py --plan plan.json --strategy-plan ../adaptive_replay/plan.json --reference <original-complete-roster-root> --bar-cache <existing-bar-cache> --factor-cache <existing-factor-cache> --output <new-output-directory>
```

The historical fixed source pins remain immutable; the diagnostic separately
verifies current installed component revisions and unchanged parser/strategy
fingerprints. It is not a new economic driver, source admission, or permission to
substitute unknown coverage with known-empty NEWS.

## Bounded publication-time-proxy diagnostic

The [October 15 report](../../docs/PUBLICATION-PROXY-2026-10-15.md) records nine
actual model replies and three source-missing no-calls on the original twelve
candidates. This separate reconstruction does not admit PUBLICATION_ONLY text
to the strict current-context service or claim native SIM/economic completion.

`tools/reconstruct_context.py prepare|finish` takes `--baseline`, `--sources`,
`--admission-result` and create-only `--output`. It binds the original candidate
IDs/geometry, prior seals and explicit unknown source coverage. Source selection
cannot use a future item, exceed the 24-hour NEWS / 31-day MACRO lookbacks, or
silently replace a missing item with an empty feed. `finish` validates separate
eligible-only `reviews.jsonl` and zero-cost `no-calls.jsonl` before emitting its
explicitly noncausal diagnostic result. It never calls a provider or database.

`tools/proxy_worker.py` reuses the existing gateway and cumulative budget inside
the recorded immutable image; it is **never called from tests or CI**. It checks
raw public input hashes, source selection, the exact twelve-candidate roster and
initial-versus-current seals before requests. It reads only protected secret
mounts and uses a create-only one-shot marker. No migrations or budget resets
exist in this path. The optional `--prior-failed-run` is solely the owner's
explicit October 15 credential correction: it retains the two authentication
failures/holds, subtracts them from the same cap and forbids chained corrections.
It is not general permission to restart or repeat the completed experiment.
