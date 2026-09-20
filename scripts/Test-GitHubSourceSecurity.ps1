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

function Get-PaginatedObjectCount {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$Description
    )

    # --slurp collects every page into one JSON document. We count the parsed
    # objects locally and intentionally never emit alert payloads.
    $payload = Invoke-GitHubReadOnlyApi -Description $Description -Arguments @(
        "--paginate", "--slurp",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        $Endpoint
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
        throw "GitHub returned an invalid paginated alert response for $Description"
    }
}

function Get-OpenDependabotAlertCount {
    param(
        [Parameter(Mandatory = $true)][string]$Repository
    )

    return Get-PaginatedObjectCount -Description "$Repository Dependabot alerts" -Endpoint "repos/$Repository/dependabot/alerts?state=open&per_page=100"
}

function Get-OpenSecretScanningAlertCount {
    param(
        [Parameter(Mandatory = $true)][string]$Repository
    )

    # GitHub's explicit redaction flag prevents literal secret material from
    # entering this process; the verifier stores and emits only the count.
    return Get-PaginatedObjectCount -Description "$Repository redacted Secret Scanning alerts" -Endpoint "repos/$Repository/secret-scanning/alerts?state=open&hide_secret=true&per_page=100"
}

function Get-MainBranchProtection {
    param(
        [Parameter(Mandatory = $true)][string]$Repository
    )

    $protectionPayload = Invoke-GitHubReadOnlyApi -Description "$Repository main branch protection" -Arguments @(
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        "repos/$Repository/branches/main/protection"
    )
    $signaturePayload = Invoke-GitHubReadOnlyApi -Description "$Repository main required signatures" -Arguments @(
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        "repos/$Repository/branches/main/protection/required_signatures"
    )
    try {
        $protection = $protectionPayload | ConvertFrom-Json
        $signatures = $signaturePayload | ConvertFrom-Json
    }
    catch {
        throw "GitHub returned invalid main branch protection data for $Repository"
    }
    $reviewProtection = $protection.PSObject.Properties["required_pull_request_reviews"]
    $statusCheckProtection = $protection.PSObject.Properties["required_status_checks"]
    $hasRequiredReviews = $null -ne $reviewProtection -and $null -ne $reviewProtection.Value
    $hasRequiredChecks = $null -ne $statusCheckProtection -and $null -ne $statusCheckProtection.Value
    return [pscustomobject]@{
        EnforceAdmins = $protection.enforce_admins.enabled
        NoForcePush = -not $protection.allow_force_pushes.enabled
        NoDeletion = -not $protection.allow_deletions.enabled
        RequiredSignatures = $signatures.enabled
        DirectMainDelivery = -not ($hasRequiredReviews -or $hasRequiredChecks)
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
    $openSecretAlerts = Get-OpenSecretScanningAlertCount -Repository $repository
    $branchProtection = Get-MainBranchProtection -Repository $repository

    if ($secretScanning -ne "enabled") { $failures.Add("${repository}: Secret Scanning is not enabled") }
    if ($pushProtection -ne "enabled") { $failures.Add("${repository}: Secret Scanning Push Protection is not enabled") }
    if ($dependabotUpdates -ne "enabled") { $failures.Add("${repository}: Dependabot security updates are not enabled") }
    if ($openAlerts -ne 0) { $failures.Add("${repository}: $openAlerts open Dependabot alert(s)") }
    if ($openSecretAlerts -ne 0) { $failures.Add("${repository}: $openSecretAlerts open redacted Secret Scanning alert(s)") }
    if (-not $branchProtection.EnforceAdmins) { $failures.Add("${repository}: main branch protection does not apply to administrators") }
    if (-not $branchProtection.NoForcePush) { $failures.Add("${repository}: main branch permits force pushes") }
    if (-not $branchProtection.NoDeletion) { $failures.Add("${repository}: main branch permits deletion") }
    if (-not $branchProtection.RequiredSignatures) { $failures.Add("${repository}: main branch does not require verified signatures") }
    if (-not $branchProtection.DirectMainDelivery) { $failures.Add("${repository}: main branch protection does not match direct signed delivery policy") }

    [pscustomobject]@{
        Repository = $repository
        SecretScanning = $secretScanning
        PushProtection = $pushProtection
        DependabotSecurityUpdates = $dependabotUpdates
        OpenDependabotAlerts = $openAlerts
        OpenRedactedSecretScanningAlerts = $openSecretAlerts
        MainSignatureProtection = $branchProtection.RequiredSignatures
        MainNoForcePush = $branchProtection.NoForcePush
        MainNoDeletion = $branchProtection.NoDeletion
    }
}

($rows | Format-Table -AutoSize | Out-String -Width 240).TrimEnd() | Write-Host
if ($failures.Count -gt 0) {
    throw "GitHub source-security gate failed:`n$($failures -join [Environment]::NewLine)"
}

Write-Host "GitHub source-security gate passed for $($rows.Count) current-release repositories."
