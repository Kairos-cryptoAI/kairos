# Current source identity

`config/current-release.json` records the exact 14-repository source set for current
engineering work. It has no runtime authority: its classification is `ENGINEERING_ONLY`,
all readiness flags remain false, and the strategy policy remains `REJECT_ALL`.

The document distinguishes source identity from evidence. A historical deployment lock,
historical release gate, simulator result, or previous green CI run does not automatically
apply to the source identity recorded here. Evidence can support a claim only when its full
source set matches this manifest, and it still cannot authorize PAPER or LIVE by itself.

The `kairos` entry uses `SELF`. A Git object cannot contain its own eventual object ID,
so the verifier resolves that one entry to the clean `main` commit being checked. Every
other repository is pinned to a full 40-character commit ID.

`kairos-backtest` is included so that the engineering snapshot records the frozen
research checkout, but it is not a runtime dependency of the current integration gates.
Those gates deliberately leave its evaluator lock, plan, and evidence untouched.

Run the local gate from this repository when all source checkouts are siblings under
`D:\Kairos`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-CurrentRelease.ps1
```

The gate requires all listed repositories to be clean, on `main`, and exactly equal to
their local `origin/main`. It also verifies that the two `kairos-deploy` deterministic
gate locks are exact projections of the eight runtime repository revisions in this
manifest; historical gate evidence therefore cannot silently carry forward across a
dependency change. Before certifying the source identity, it also checks each tracked
source tree for a small set of high-confidence credential shapes. A match reports only
the repository, path, and pattern class; it never prints a matching value. It makes no
network calls, reads no secrets, starts no Docker services, and cannot arm EVEDEX,
PAPER, LIVE, or a simulator.

The same local gate rejects any external GitHub Action or reusable workflow reference
that is not pinned to a full 40-character Git SHA. Container actions must use a
SHA-256 digest; local actions remain within the reviewed source tree.
