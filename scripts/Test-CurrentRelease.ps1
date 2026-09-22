[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$WorkspaceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $repositoryRoot "config\current-release.json"
}
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = Split-Path -Parent $repositoryRoot
}

function Invoke-ReleaseGit {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    # Git can emit benign warnings for ignored, inaccessible cache directories.  The
    # release decision is based on its exit status and stdout, so do not let an
    # external-program stderr record become a PowerShell terminating error.
    $result = & git -C $RepositoryPath @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git -C $RepositoryPath $($Arguments -join ' ') failed: $($result -join [Environment]::NewLine)"
    }
    return ($result | Out-String).Trim()
}

function Find-TrackedCredentialPatternPaths {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string]$Pattern
    )

    # `git grep -l` deliberately returns paths, never matching text. This makes
    # the current-release receipt safe to retain even if it detects an accidental
    # committed credential. Exit code 1 is Git's documented "no matches" result.
    $paths = & git -C $RepositoryPath grep -I -l -E -- $Pattern 2>$null
    if ($LASTEXITCODE -eq 1) {
        return @()
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to perform tracked-credential pattern check in $RepositoryPath"
    }
    return @($paths | ForEach-Object { $_.ToString().Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Find-UnpinnedGitHubActions {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath
    )

    $workflowPaths = @(
        (Invoke-ReleaseGit -RepositoryPath $RepositoryPath -Arguments @("ls-files", "--", ".github/workflows")) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    foreach ($relativePath in $workflowPaths) {
        if ($relativePath -notmatch '\.ya?ml$') { continue }
        $fullPath = Join-Path $RepositoryPath $relativePath
        $lineNumber = 0
        foreach ($line in Get-Content -LiteralPath $fullPath) {
            $lineNumber++
            $match = [regex]::Match($line, '^\s*uses:\s*(?<reference>\S+)')
            if (-not $match.Success) { continue }
            $reference = $match.Groups["reference"].Value
            $isLocal = $reference.StartsWith("./", [System.StringComparison]::Ordinal)
            $isGitSha = $reference -match '^[^@\s]+@[0-9a-f]{40}$'
            $isDockerDigest = $reference -match '^docker://[^@\s]+@sha256:[0-9a-f]{64}$'
            if (-not ($isLocal -or $isGitSha -or $isDockerDigest)) {
                $findings.Add([pscustomobject]@{
                    Path = $relativePath
                    Line = $lineNumber
                    Reference = $reference
                })
            }
        }
    }
    return @($findings)
}

function Resolve-ReleaseGpgProgram {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($env:KAIROS_GPG_PROGRAM)) {
        $candidates.Add($env:KAIROS_GPG_PROGRAM)
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates.Add((Join-Path $env:ProgramFiles "Git\usr\bin\gpg.exe"))
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    $command = Get-Command gpg -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
        return $command.Source
    }
    throw "A GPG executable is required to verify current-release commit signatures"
}

function Assert-ReleaseCommitSignature {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string]$RepositoryName,
        [Parameter(Mandatory = $true)][string]$GpgProgram,
        [Parameter(Mandatory = $true)][string]$ExpectedFingerprint
    )

    # GPG writes normal verification diagnostics to stderr.  With
    # ErrorActionPreference=Stop, Windows PowerShell can turn that native stderr
    # into a terminating NativeCommandError even when stderr is redirected.
    # Keep native diagnostics non-terminating only for these two calls; the
    # signature decision below is based on Git's exit code and metadata.
    $previousErrorActionPreference = $ErrorActionPreference
    $nativeErrorPreference = Get-Variable -Name "PSNativeCommandUseErrorActionPreference" -ErrorAction SilentlyContinue
    $hasNativeErrorPreference = $null -ne $nativeErrorPreference
    if ($hasNativeErrorPreference) {
        $previousNativeErrorPreference = $nativeErrorPreference.Value
    }
    try {
        $ErrorActionPreference = "Continue"
        if ($hasNativeErrorPreference) {
            Set-Variable -Name "PSNativeCommandUseErrorActionPreference" -Value $false -Scope Local
        }
        $null = & git -C $RepositoryPath -c "gpg.program=$GpgProgram" verify-commit HEAD 2>$null
        $verifyExitCode = $LASTEXITCODE
        if ($verifyExitCode -ne 0) {
            throw "$RepositoryName HEAD does not have a verifiable trusted GPG signature"
        }
        $signatureMetadata = & git -C $RepositoryPath -c "gpg.program=$GpgProgram" log -1 --format='%G?::%GF' 2>$null
        $metadataExitCode = $LASTEXITCODE
        if ($metadataExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($signatureMetadata)) {
            throw "$RepositoryName HEAD signature metadata could not be read"
        }
        $parts = @($signatureMetadata.Trim() -split '::', 2)
        if ($parts.Count -ne 2 -or $parts[0] -ne "G" -or $parts[1].ToUpperInvariant() -ne $ExpectedFingerprint.ToUpperInvariant()) {
            throw "$RepositoryName HEAD is not signed by the required current-release key"
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hasNativeErrorPreference) {
            Set-Variable -Name "PSNativeCommandUseErrorActionPreference" -Value $previousNativeErrorPreference -Scope Local
        }
    }
}

$manifestFullPath = [System.IO.Path]::GetFullPath($ManifestPath)
$workspaceFullPath = [System.IO.Path]::GetFullPath($WorkspaceRoot)
if (-not (Test-Path -LiteralPath $manifestFullPath -PathType Leaf)) {
    throw "Current-release manifest does not exist: $manifestFullPath"
}
if (-not (Test-Path -LiteralPath $workspaceFullPath -PathType Container)) {
    throw "Workspace root does not exist: $workspaceFullPath"
}

$manifest = Get-Content -LiteralPath $manifestFullPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 2 -or $manifest.kind -ne "CURRENT_SOURCE_IDENTITY") {
    throw "Unsupported current-release manifest schema"
}
if ([string]::IsNullOrWhiteSpace($manifest.releaseId) -or $manifest.releaseId -notmatch '^engineering-main-\d{8}T\d{6}Z$') {
    throw "Current-release manifest requires a stable engineering release identifier"
}
if ($manifest.scope.classification -ne "ENGINEERING_ONLY" -or
    $manifest.scope.tradingAuthority -ne "NONE" -or
    $manifest.scope.simulatorAuthority -ne "NONE") {
    throw "The source-identity manifest must not grant runtime authority"
}
if ($manifest.readiness.technicalPaperReady -or $manifest.readiness.paperQualified -or
    $manifest.readiness.alphaReady -or $manifest.readiness.liveReady -or
    $manifest.readiness.strategyPolicy -ne "REJECT_ALL") {
    throw "The source-identity manifest must not grant trading readiness"
}
$signing = $manifest.signing
if ($null -eq $signing -or $signing.required -ne $true -or
    [string]::IsNullOrWhiteSpace($signing.trustedFingerprint) -or
    $signing.trustedFingerprint -notmatch '^[0-9A-F]{40}$') {
    throw "Current-release manifest requires an exact trusted GPG signing fingerprint"
}
$gpgProgram = Resolve-ReleaseGpgProgram

$expectedNames = @(
    "kairos", "kairos-aggregator", "kairos-backtest", "kairos-core", "kairos-deploy",
    "kairos-execution-engine", "kairos-llm", "kairos-macro-strategist", "kairos-persistence",
    "kairos-quant-scouts", "kairos-risk-manager", "kairos-router", "kairos-strategy-engine", "kairos-text-scouts"
)
$entries = @($manifest.repositories)
if ($entries.Count -ne $expectedNames.Count) { throw "Expected $($expectedNames.Count) release repositories" }
if (@($entries.name | Sort-Object -Unique).Count -ne $expectedNames.Count) { throw "Release repository names are not unique" }
if ((Compare-Object -ReferenceObject ($expectedNames | Sort-Object) -DifferenceObject ($entries.name | Sort-Object))) {
    throw "Release repository set differs from the required Kairos source set"
}
$entryByName = @{}
foreach ($entry in $entries) {
    $entryByName[$entry.name] = $entry
}

foreach ($entry in $entries) {
    if ([string]::IsNullOrWhiteSpace($entry.directory) -or
        [string]::IsNullOrWhiteSpace($entry.origin) -or
        [string]::IsNullOrWhiteSpace($entry.revision)) {
        throw "Incomplete source identity for $($entry.name)"
    }
    if ($entry.directory -match '[\\/]' -or $entry.directory -eq '.' -or $entry.directory -eq '..') {
        throw "Unsafe repository directory in manifest: $($entry.directory)"
    }
    if ($entry.revision -ne "SELF" -and $entry.revision -notmatch '^[0-9a-f]{40}$') {
        throw "Invalid revision for $($entry.name)"
    }
    if ($entry.revision -eq "SELF" -and $entry.name -ne "kairos") {
        throw "Only the meta repository may use SELF"
    }
    if ($entry.origin -ne "https://github.com/Kairos-cryptoAI/$($entry.name).git") {
        throw "Unexpected canonical source origin for $($entry.name)"
    }

    $repositoryPath = Join-Path $workspaceFullPath $entry.directory
    if (-not (Test-Path -LiteralPath $repositoryPath -PathType Container)) {
        throw "Missing release repository $($entry.name): $repositoryPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryPath '.git'))) {
        throw "Release path is not a Git checkout: $repositoryPath"
    }

    $branch = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("branch", "--show-current")
    if ($branch -ne "main") { throw "$($entry.name) is not on main (found '$branch')" }
    $dirty = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("status", "--porcelain=v1", "--untracked-files=no")
    if (-not [string]::IsNullOrWhiteSpace($dirty)) { throw "$($entry.name) has uncommitted changes" }

    $head = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("rev-parse", "HEAD")
    $originMain = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("rev-parse", "origin/main")
    if ($head -ne $originMain) { throw "$($entry.name) HEAD does not match origin/main" }
    if ($entry.revision -ne "SELF" -and $head -ne $entry.revision) {
        throw "$($entry.name) HEAD does not match the current-release manifest"
    }
    Assert-ReleaseCommitSignature -RepositoryPath $repositoryPath -RepositoryName $entry.name -GpgProgram $gpgProgram -ExpectedFingerprint $signing.trustedFingerprint
}

# Workflow actions execute with repository credentials. Every external action or
# reusable workflow must therefore be bound to an immutable Git SHA (or, for a
# container action, a content digest). Local actions are reviewed with their
# containing source tree and are allowed by the same source-identity boundary.
foreach ($entry in $entries) {
    $repositoryPath = Join-Path $workspaceFullPath $entry.directory
    foreach ($finding in Find-UnpinnedGitHubActions -RepositoryPath $repositoryPath) {
        throw "Unpinned GitHub Action reference in $($entry.name)/$($finding.Path):$($finding.Line) ($($finding.Reference))"
    }
}

# Source identity is not sufficient to certify an engineering release if a
# credential has been committed into any tracked source file. Keep this small,
# conservative, and path-only: this verifier must never print matching values.
$credentialPatterns = [ordered]@{
    "openai-style-secret" = "sk-[A-Za-z0-9_-]{20,}"
    "github-classic-token" = "ghp_[A-Za-z0-9]{30,}"
    "github-fine-grained-token" = "github_pat_[A-Za-z0-9_]{30,}"
    "slack-token" = "xox[baprs]-[A-Za-z0-9-]{20,}"
    "private-key-pem" = "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"
    "bearer-token" = "Bearer[[:space:]]+[A-Za-z0-9._~-]{20,}"
}
foreach ($entry in $entries) {
    $repositoryPath = Join-Path $workspaceFullPath $entry.directory
    foreach ($patternId in $credentialPatterns.Keys) {
        $matchingPaths = Find-TrackedCredentialPatternPaths -RepositoryPath $repositoryPath -Pattern $credentialPatterns[$patternId]
        foreach ($matchingPath in $matchingPaths) {
            throw "Tracked credential-like pattern '$patternId' detected in $($entry.name)/$matchingPath; source identity cannot be certified"
        }
    }
}

# Both deterministic gates are built in kairos-deploy, but their source locks
# must be a literal projection of the runtime repositories recorded above. This
# catches a stale gate dependency before a historical green gate can be cited
# for a newer top-level source identity.
$runtimeGateNames = @(
    "kairos-core", "kairos-persistence", "kairos-strategy-engine", "kairos-router",
    "kairos-llm", "kairos-aggregator", "kairos-risk-manager", "kairos-execution-engine"
)
$deployRoot = Join-Path $workspaceFullPath $entryByName["kairos-deploy"].directory
$gateSpecifications = @(
    [pscustomobject]@{
        FileName = "current-release-gate.sources.lock.json"
        Purpose = "current-release-reject-all-integration-gate"
        Classification = "ENGINEERING_ONLY"
    },
    [pscustomobject]@{
        FileName = "sim-full-path.sources.lock.json"
        Purpose = "isolated-full-path-market-data-simulator"
        Classification = "SIMULATED"
    }
)
foreach ($gate in $gateSpecifications) {
    $gatePath = Join-Path $deployRoot $gate.FileName
    if (-not (Test-Path -LiteralPath $gatePath -PathType Leaf)) {
        throw "Current-release gate source lock is missing: $gatePath"
    }
    $gateLock = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json
    if ($gateLock.purpose -ne $gate.Purpose -or $gateLock.classification -ne $gate.Classification) {
        throw "Current-release gate source lock has an unexpected identity: $($gate.FileName)"
    }
    $readiness = $gateLock.PSObject.Properties["readiness"].Value
    if ($null -eq $readiness -or $readiness.paper_qualified -or $readiness.alpha_ready -or
        $readiness.live_ready -or $readiness.strategy_policy -ne "REJECT_ALL") {
        throw "Current-release gate source lock must remain fail-closed: $($gate.FileName)"
    }
    $dependencies = $gateLock.PSObject.Properties["dependencies"].Value
    if ($null -eq $dependencies) {
        throw "Current-release gate source lock has no dependencies: $($gate.FileName)"
    }
    $dependencyNames = @($dependencies.PSObject.Properties | ForEach-Object { $_.Name })
    if (Compare-Object -ReferenceObject ($runtimeGateNames | Sort-Object) -DifferenceObject ($dependencyNames | Sort-Object)) {
        throw "Current-release gate dependency set differs from the runtime projection: $($gate.FileName)"
    }
    foreach ($name in $runtimeGateNames) {
        $dependency = $dependencies.PSObject.Properties[$name].Value
        $expected = $entryByName[$name]
        $expectedRepository = $expected.origin
        if ($expectedRepository.EndsWith(".git", [System.StringComparison]::Ordinal)) {
            $expectedRepository = $expectedRepository.Substring(0, $expectedRepository.Length - 4)
        }
        if ($dependency.repository -ne $expectedRepository -or $dependency.revision -ne $expected.revision) {
            throw "Current-release gate dependency does not match the manifest: $($gate.FileName) / $name"
        }
    }
}

Write-Host "Current release source identity verified across $($entries.Count) clean main repositories."
