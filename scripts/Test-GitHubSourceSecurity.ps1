[CmdletBinding()]
param(
    [string]$ManifestPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $repositoryRoot "config\current-release.json"
}
$manifestFullPath = [System.IO.Path]::GetFullPath($ManifestPath)
if (-not (Test-Path -LiteralPath $manifestFullPath -PathType Leaf)) {
    throw "Current-release manifest does not exist: $manifestFullPath"
}
if ($null -eq (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI is required for the read-only source-security check"
}

$manifest = Get-Content -LiteralPath $manifestFullPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 2 -or $manifest.kind -ne "CURRENT_SOURCE_IDENTITY") {
    throw "Unsupported current-release manifest schema"
}
$entries = @($manifest.repositories)
if ($entries.Count -ne 14 -or @($entries.name | Sort-Object -Unique).Count -ne 14) {
    throw "Expected exactly 14 unique current-release repositories"
}

function Invoke-GitHubReadOnlyApi {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $result = & gh api @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub read-only API request failed for $Description"
    }
    return $result
}

function Get-OpenDependabotAlertCount {
    param(
        [Parameter(Mandatory = $true)][string]$Repository
    )

    # --slurp collects every page into one JSON document. We count the parsed
    # objects locally and intentionally never emit advisory payloads.
    $payload = Invoke-GitHubReadOnlyApi -Description "$Repository Dependabot alerts" -Arguments @(
        "--paginate", "--slurp",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        "repos/$Repository/dependabot/alerts?state=open&per_page=100"
    )
    try {
        $pages = $payload | ConvertFrom-Json -NoEnumerate
        if ($pages -isnot [System.Array]) {
            throw "Dependabot pagination response was not an array"
        }
        $total = 0
        for ($index = 0; $index -lt $pages.Count; $index++) {
            $total += @($pages[$index]).Count
        }
        return $total
    }
    catch {
        throw "GitHub returned an invalid Dependabot alert response for $Repository"
    }
}

$failures = [System.Collections.Generic.List[string]]::new()
$rows = foreach ($entry in $entries | Sort-Object name) {
    if ([string]::IsNullOrWhiteSpace($entry.origin) -or $entry.origin -notmatch '^https://github\.com/(?<owner>[^/]+)/(?<repository>[^/]+)\.git$') {
        throw "Current-release entry has no safe GitHub origin: $($entry.name)"
    }
    $repository = "$($Matches.owner)/$($Matches.repository)"
    $payload = Invoke-GitHubReadOnlyApi -Description "$repository security settings" -Arguments @(
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        "repos/$repository"
    )
    try {
        $metadata = $payload | ConvertFrom-Json
    }
    catch {
        throw "GitHub returned an invalid repository response for $repository"
    }

    $analysis = $metadata.security_and_analysis
    $secretScanning = $analysis.secret_scanning.status
    $pushProtection = $analysis.secret_scanning_push_protection.status
    $dependabotUpdates = $analysis.dependabot_security_updates.status
    $openAlerts = Get-OpenDependabotAlertCount -Repository $repository

    if ($secretScanning -ne "enabled") { $failures.Add("${repository}: Secret Scanning is not enabled") }
    if ($pushProtection -ne "enabled") { $failures.Add("${repository}: Secret Scanning Push Protection is not enabled") }
    if ($dependabotUpdates -ne "enabled") { $failures.Add("${repository}: Dependabot security updates are not enabled") }
    if ($openAlerts -ne 0) { $failures.Add("${repository}: $openAlerts open Dependabot alert(s)") }

    [pscustomobject]@{
        Repository = $repository
        SecretScanning = $secretScanning
        PushProtection = $pushProtection
        DependabotSecurityUpdates = $dependabotUpdates
        OpenDependabotAlerts = $openAlerts
    }
}

$rows | Format-Table -AutoSize
if ($failures.Count -gt 0) {
    throw "GitHub source-security gate failed:`n$($failures -join [Environment]::NewLine)"
}

Write-Host "GitHub source-security gate passed for $($rows.Count) current-release repositories."
