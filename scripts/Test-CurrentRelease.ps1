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

    $result = & git -C $RepositoryPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git -C $RepositoryPath $($Arguments -join ' ') failed: $($result -join [Environment]::NewLine)"
    }
    return ($result | Out-String).Trim()
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
if ($manifest.schemaVersion -ne 1) { throw "Unsupported current-release manifest schema" }
if ($manifest.readiness.technicalPaperReady -or $manifest.readiness.paperQualified -or
    $manifest.readiness.alphaReady -or $manifest.readiness.liveReady -or
    $manifest.readiness.strategyPolicy -ne "REJECT_ALL") {
    throw "The source-identity manifest must not grant trading readiness"
}

$expectedNames = @(
    "kairos", "kairos-aggregator", "kairos-backtest", "kairos-core", "kairos-deploy",
    "kairos-execution-engine", "kairos-llm", "kairos-macro", "kairos-persistence",
    "kairos-quant", "kairos-risk", "kairos-router", "kairos-strategy-engine", "kairos-text-scouts"
)
$entries = @($manifest.repositories)
if ($entries.Count -ne $expectedNames.Count) { throw "Expected $($expectedNames.Count) release repositories" }
if (@($entries.name | Sort-Object -Unique).Count -ne $expectedNames.Count) { throw "Release repository names are not unique" }
if ((Compare-Object -ReferenceObject ($expectedNames | Sort-Object) -DifferenceObject ($entries.name | Sort-Object))) {
    throw "Release repository set differs from the required Kairos source set"
}

foreach ($entry in $entries) {
    if ([string]::IsNullOrWhiteSpace($entry.directory) -or [string]::IsNullOrWhiteSpace($entry.revision)) {
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

    $repositoryPath = Join-Path $workspaceFullPath $entry.directory
    if (-not (Test-Path -LiteralPath $repositoryPath -PathType Container)) {
        throw "Missing release repository $($entry.name): $repositoryPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryPath '.git'))) {
        throw "Release path is not a Git checkout: $repositoryPath"
    }

    $branch = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("branch", "--show-current")
    if ($branch -ne "main") { throw "$($entry.name) is not on main (found '$branch')" }
    $dirty = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("status", "--porcelain=v1")
    if (-not [string]::IsNullOrWhiteSpace($dirty)) { throw "$($entry.name) has uncommitted changes" }

    $head = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("rev-parse", "HEAD")
    $originMain = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("rev-parse", "origin/main")
    if ($head -ne $originMain) { throw "$($entry.name) HEAD does not match origin/main" }
    if ($entry.revision -ne "SELF" -and $head -ne $entry.revision) {
        throw "$($entry.name) HEAD does not match the current-release manifest"
    }
}

Write-Host "Current release source identity verified across $($entries.Count) clean main repositories."
