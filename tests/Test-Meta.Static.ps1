[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runnerPath = Join-Path $repoRoot "scripts\Test-Kairos.ps1"
$manifestPath = Join-Path $repoRoot "config\repositories.json"

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

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1) { throw "Unexpected manifest schema" }
if ($manifest.requiredUvVersion -ne "0.12.3") { throw "Unexpected uv version" }
if (@($manifest.pythonVersions) -join "," -ne "3.11,3.14") { throw "Unexpected Python matrix" }
if (@($manifest.repositories).Count -ne 11) { throw "Expected 11 Python repositories" }
if (@($manifest.repositories.name | Sort-Object -Unique).Count -ne 11) {
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
foreach ($requiredFragment in @("lock", "--check", "--locked", "format", "--check", "mypy", "bandit", "pytest", "build", "--no-sources", "Out-Host", "--no-sync")) {
    if (-not $runnerText.Contains($requiredFragment)) {
        throw "Runner is missing required command fragment: $requiredFragment"
    }
}
if (-not $runnerText.Contains('@("mypy", "--python-version", $version, $entry.source)')) {
    throw "Runner must type-check against the selected Python matrix version"
}
foreach ($forbiddenFragment in @("reset --hard", "checkout --", "clean -", "Get-Content .env", "docker compose")) {
    if ($runnerText.Contains($forbiddenFragment)) {
        throw "Runner contains forbidden mutation or secret access: $forbiddenFragment"
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
