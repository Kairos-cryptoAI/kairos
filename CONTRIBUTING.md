# Contributing to Kairos

Kairos changes usually cross repository boundaries. Keep contracts backward-compatible, pin
internal Git dependencies to reviewed full commit SHAs, and update consumers in dependency
order. Do not copy a `kairos-core` message definition into a service.

## Toolchain and checks

- Use the repository-pinned `uv` version (currently 0.12.3), not ad-hoc `pip install` flows.
- Python 3.11 is the declared development version; CI also verifies Python 3.14 and Windows.
- Commit `uv.lock` and use `uv lock --check` / `uv sync --locked` in verification.
- Keep Ruff, Ruff format, mypy, Bandit, pytest and package build green.
- Add network-free unit tests for deterministic rules, ACK/replay behavior and degradation paths.
- Run live provider or exchange tests only in an explicitly provisioned environment.

From the meta-repository on Windows:

```powershell
# All eleven Python repositories, both supported CI versions.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Kairos.ps1

# One repository and one version while iterating.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Kairos.ps1 `
  -Repository kairos-execution-engine -PythonVersion 3.11 -FailFast

# Static runner/manifest/link validation.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\Test-Meta.Static.ps1
```

The runner is intentionally non-destructive: it reports dirty worktrees, does not stage or
clean files, does not read secrets, and does not require Docker. The persistence repository's
Docker-backed integration suite is a separate opt-in gate.

## Pull requests and commits

- Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `ci:`, `chore:`).
- Sign commits with the contributor's configured GPG identity.
- Land cross-repository changes on `main` in dependency order only after dependent SHAs are stable.
- Explain contract changes, migration/rollback order, checks run and remaining live-test gaps.
- Do not claim production readiness from unit tests or green CI alone.

Recommended dependency order is `kairos-core`, then `kairos-llm`, then services that consume
them, followed by deploy/meta manifests. Re-lock each consumer after updating a source SHA.

## Safety boundaries

- Execution defaults to dry-run. Never commit API keys, wallets, seed phrases, `.env` files or
  recorded authenticated traffic.
- Do not bypass Risk Manager validation, account freshness checks, reconciliation failure
  handling, or `SystemMode` restrictions.
- `LOCAL_QUANT_MODE` must block new exposure while still allowing protective close/reduce-only
  actions where the contract distinguishes them.
- Redis ACKs occur only after complete processing and required publishes succeed.
- Until durable inbox/outbox integration is present end-to-end, preserve deterministic IDs and
  replay-safe behavior and document any process-local deduplication window.
