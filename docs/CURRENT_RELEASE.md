# Current release source identity

`config/current-release.json` records the exact 14-repository source set used by the
current engineering release gate. It is deliberately a source-identity document, not an
approval to trade: every readiness flag remains false and the strategy policy remains
`REJECT_ALL`.

The `kairos` entry uses `SELF`. A Git object cannot contain its own eventual object ID,
so the verifier resolves that one entry to the clean `main` commit being checked. Every
other repository is pinned to a full 40-character commit ID.

Run the local gate from this repository when all source checkouts are siblings under
`D:\Kairos`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-CurrentRelease.ps1
```

The gate requires all listed repositories to be clean, on `main`, and exactly equal to
their local `origin/main`. It makes no network calls, reads no secrets, starts no Docker
services, and cannot arm EVEDEX, PAPER, LIVE, or a simulator.
