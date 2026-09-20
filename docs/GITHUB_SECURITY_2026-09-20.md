# GitHub source-security baseline — 2026-09-20

## Scope and result

At `2026-09-20T18:16:36Z`, the GitHub repository settings for every source in
the current 14-repository Kairos release set were changed and then independently
read back through the GitHub REST API. The following built-in protections are
now `enabled` for each repository:

- GitHub Secret Scanning;
- Secret Scanning Push Protection;
- Dependabot security updates.

The verified scope is `kairos`, `kairos-core`, `kairos-strategy-engine`,
`kairos-backtest`, `kairos-router`, `kairos-aggregator`,
`kairos-risk-manager`, `kairos-execution-engine`, `kairos-text-scouts`,
`kairos-macro-strategist`, `kairos-quant-scouts`, `kairos-persistence`,
`kairos-deploy`, and `kairos-llm`.

At `2026-09-20T18:19:37Z`, a separate read-only query of the open Dependabot
alerts endpoint returned zero open alerts for every repository in that scope.
This is an observation at that timestamp, not a guarantee about future alert
state.

At `2026-09-20T18:47:56Z`, the open Secret Scanning alert endpoint was queried
with GitHub's `hide_secret=true` redaction option. It returned zero open alerts
for every repository in scope; no literal secret material was retrieved or
reported.

At `2026-09-20T19:02:17Z`, an immediate readback confirmed that all 14 `main`
branches have the same compatible protection profile: protection applies to
administrators, force pushes and branch deletion are disabled, and GitHub
requires verified commit signatures.
The profile deliberately has no required pull request review or required status
check, so it preserves the approved direct, signed delivery to `main`.

No secret alerts or credential values were enumerated while producing this
receipt. The local current-release verifier additionally rejects a release if a
small high-confidence credential pattern appears in any tracked source file;
its diagnostics include only the repository, path, and pattern class.

Repeat the online, read-only settings and Dependabot-alert check with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitHubSourceSecurity.ps1
```

The command reads repository metadata, the open Dependabot alert count, and the
open Secret Scanning alert count with GitHub's `hide_secret=true` redaction flag.
It does not change GitHub settings, retrieve literal secret values, read local
secret files, or contact a trading or model provider.

## Deliberate limits

This is source-code protection, not a trading authorization or a replacement
for an independent security audit. It does not assert that there are no historic
secrets, no vulnerabilities, or no runtime configuration issues. The limited
branch protection profile preserves direct signed commits to `main`; requiring
pull requests or status checks remains a separate workflow decision.

It does not change any readiness flag. The following remain true:

```text
PAPER_QUALIFIED=false
ALPHA_READY=false
LIVE_READY=false
STRATEGY_POLICY=REJECT_ALL
```

The managed deep-scan worker was unavailable on this host because it requires a
managed filesystem permission profile. That environmental limitation must be
resolved before an independent deep audit can be cited as complete.
