[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runnerPath = Join-Path $repoRoot "scripts\Test-Kairos.ps1"
$manifestPath = Join-Path $repoRoot "config\repositories.json"
$currentReleasePath = Join-Path $repoRoot "config\current-release.json"
$currentReleaseVerifierPath = Join-Path $repoRoot "scripts\Test-CurrentRelease.ps1"
$githubSecurityVerifierPath = Join-Path $repoRoot "scripts\Test-GitHubSourceSecurity.ps1"

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $runnerPath,
    [ref]$tokens,
    [ref]$parseErrors
) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw "PowerShell runner parse errors: $($parseErrors -join '; ')"
}

$releaseTokens = $null
$releaseParseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $currentReleaseVerifierPath,
    [ref]$releaseTokens,
    [ref]$releaseParseErrors
) | Out-Null
if ($releaseParseErrors.Count -gt 0) {
    throw "Current-release verifier parse errors: $($releaseParseErrors -join '; ')"
}

$githubSecurityTokens = $null
$githubSecurityParseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $githubSecurityVerifierPath,
    [ref]$githubSecurityTokens,
    [ref]$githubSecurityParseErrors
) | Out-Null
if ($githubSecurityParseErrors.Count -gt 0) {
    throw "GitHub source-security verifier parse errors: $($githubSecurityParseErrors -join '; ')"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1) { throw "Unexpected manifest schema" }
if ($manifest.requiredUvVersion -ne "0.12.3") { throw "Unexpected uv version" }
if (@($manifest.pythonVersions) -join "," -ne "3.11,3.14") { throw "Unexpected Python matrix" }
if (@($manifest.repositories).Count -ne 12) { throw "Expected 12 Python repositories" }
if (@($manifest.repositories.name | Sort-Object -Unique).Count -ne 12) {
    throw "Repository names are not unique"
}
foreach ($entry in $manifest.repositories) {
    if ([string]::IsNullOrWhiteSpace($entry.source)) { throw "Missing source for $($entry.name)" }
    if (@($entry.pytestArgs).Count -eq 0) { throw "Missing pytestArgs for $($entry.name)" }
}

& $runnerPath -ManifestPath $manifestPath -ValidateOnly
if ($LASTEXITCODE -ne 0) { throw "Runner manifest validation failed" }
& $runnerPath -Repository kairos-core -PythonVersion 3.11 -ValidateOnly
if ($LASTEXITCODE -ne 0) { throw "Runner default manifest path failed" }

$runnerText = Get-Content -LiteralPath $runnerPath -Raw
$currentReleaseVerifierText = Get-Content -LiteralPath $currentReleaseVerifierPath -Raw
foreach ($requiredFragment in @("lock", "--check", "--locked", "format", "--check", "mypy", "bandit", "pytest", "build", "--no-sources", "Out-Host", "--no-sync")) {
    if (-not $runnerText.Contains($requiredFragment)) {
        throw "Runner is missing required command fragment: $requiredFragment"
    }
}

$currentRelease = Get-Content -LiteralPath $currentReleasePath -Raw | ConvertFrom-Json
if ($currentRelease.schemaVersion -ne 2 -or $currentRelease.kind -ne "CURRENT_SOURCE_IDENTITY") {
    throw "Unexpected current-release manifest schema"
}
if ([string]::IsNullOrWhiteSpace($currentRelease.releaseId) -or
    $currentRelease.releaseId -notmatch '^engineering-main-\d{8}T\d{6}Z$') {
    throw "Current-release manifest requires an engineering release identifier"
}
if ($currentRelease.scope.classification -ne "ENGINEERING_ONLY" -or
    $currentRelease.scope.tradingAuthority -ne "NONE" -or
    $currentRelease.scope.simulatorAuthority -ne "NONE") {
    throw "Current-release manifest must not grant runtime authority"
}
if (@($currentRelease.repositories).Count -ne 14) { throw "Expected 14 current-release repositories" }
$expectedReleaseNames = @(
    "kairos", "kairos-aggregator", "kairos-backtest", "kairos-core", "kairos-deploy",
    "kairos-execution-engine", "kairos-llm", "kairos-macro-strategist", "kairos-persistence",
    "kairos-quant-scouts", "kairos-risk-manager", "kairos-router", "kairos-strategy-engine", "kairos-text-scouts"
)
if ((Compare-Object -ReferenceObject ($expectedReleaseNames | Sort-Object) -DifferenceObject ($currentRelease.repositories.name | Sort-Object))) {
    throw "Current-release repository set is incomplete or unexpected"
}
foreach ($entry in $currentRelease.repositories) {
    if ([string]::IsNullOrWhiteSpace($entry.directory) -or
        [string]::IsNullOrWhiteSpace($entry.origin) -or
        [string]::IsNullOrWhiteSpace($entry.revision)) {
        throw "Current-release entry is incomplete: $($entry.name)"
    }
    if ($entry.revision -ne "SELF" -and $entry.revision -notmatch '^[0-9a-f]{40}$') {
        throw "Current-release revision is invalid: $($entry.name)"
    }
    if ($entry.origin -ne "https://github.com/Kairos-cryptoAI/$($entry.name).git") {
        throw "Current-release source origin is invalid: $($entry.name)"
    }
}
if ($currentRelease.readiness.technicalPaperReady -or $currentRelease.readiness.paperQualified -or
    $currentRelease.readiness.alphaReady -or $currentRelease.readiness.liveReady -or
    $currentRelease.readiness.strategyPolicy -ne "REJECT_ALL") {
    throw "Current-release manifest must not grant trading readiness"
}
if (-not $runnerText.Contains('@("mypy", "--python-version", $version, $entry.source)')) {
    throw "Runner must type-check against the selected Python matrix version"
}
foreach ($forbiddenFragment in @("reset --hard", "checkout --", "clean -", "Get-Content .env", "docker compose")) {
    if ($runnerText.Contains($forbiddenFragment)) {
        throw "Runner contains forbidden mutation or secret access: $forbiddenFragment"
    }
}
foreach ($requiredFragment in @("current-release-gate.sources.lock.json", "sim-full-path.sources.lock.json", "runtimeGateNames")) {
    if (-not $currentReleaseVerifierText.Contains($requiredFragment)) {
        throw "Current-release verifier is missing required source-projection check: $requiredFragment"
    }
}
foreach ($requiredFragment in @("Find-TrackedCredentialPatternPaths", "openai-style-secret", "private-key-pem", 'git -C $RepositoryPath grep -I -l -E')) {
    if (-not $currentReleaseVerifierText.Contains($requiredFragment)) {
        throw "Current-release verifier is missing required tracked-credential check: $requiredFragment"
    }
}
if (-not $currentReleaseVerifierText.Contains("never print matching values")) {
    throw "Current-release credential check must remain path-only"
}
foreach ($requiredFragment in @("Find-UnpinnedGitHubActions", "isGitSha", "isDockerDigest", "Unpinned GitHub Action reference")) {
    if (-not $currentReleaseVerifierText.Contains($requiredFragment)) {
        throw "Current-release verifier is missing required action-pin check: $requiredFragment"
    }
}

$githubSecurityVerifierText = Get-Content -LiteralPath $githubSecurityVerifierPath -Raw
foreach ($requiredFragment in @("Get-OpenDependabotAlertCount", "security_and_analysis", "--paginate", "GitHub read-only API request")) {
    if (-not $githubSecurityVerifierText.Contains($requiredFragment)) {
        throw "GitHub source-security verifier is missing required check: $requiredFragment"
    }
}
foreach ($forbiddenFragment in @("--method PATCH", "--method POST", "--method PUT", "--method DELETE", "secret-scanning/alerts")) {
    if ($githubSecurityVerifierText.Contains($forbiddenFragment)) {
        throw "GitHub source-security verifier contains a forbidden mutation or secret-alert route: $forbiddenFragment"
    }
}

$markdownFiles = @(
    Get-Item -LiteralPath (Join-Path $repoRoot "README.md"), (Join-Path $repoRoot "CONTRIBUTING.md"), (Join-Path $repoRoot "SPEC.md")
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "docs") -Filter "*.md" -Recurse
)
$linkPattern = [regex]'\[[^\]]+\]\((?<target>(?!https?://|mailto:|#)[^)#]+)(?:#[^)]+)?\)'
foreach ($file in $markdownFiles) {
    $text = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($match in $linkPattern.Matches($text)) {
        $target = [System.Uri]::UnescapeDataString($match.Groups["target"].Value.Trim())
        $resolved = [System.IO.Path]::GetFullPath((Join-Path $file.DirectoryName $target))
        if (-not (Test-Path -LiteralPath $resolved)) {
            throw "Broken local Markdown link in $($file.FullName): $target"
        }
    }
}

Write-Host "Static runner, manifest, and local Markdown-link validation passed."
