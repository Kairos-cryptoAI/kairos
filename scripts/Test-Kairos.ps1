[CmdletBinding()]
param(
    [string]$ManifestPath = "",
    [string[]]$Repository = @(),
    [string[]]$PythonVersion = @(),
    [switch]$FailFast,
    [switch]$ValidateOnly,
    [switch]$SkipSync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $PSScriptRoot "..\config\repositories.json"
}

function Resolve-FullPath {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$BasePath)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Read-RepositoryManifest {
    param([Parameter(Mandatory)][string]$Path)

    $fullPath = Resolve-FullPath -Path $Path -BasePath (Get-Location).Path
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Repository manifest not found: $fullPath"
    }
    $manifest = Get-Content -LiteralPath $fullPath -Raw | ConvertFrom-Json
    if ($manifest.schemaVersion -ne 1) {
        throw "Unsupported manifest schemaVersion: $($manifest.schemaVersion)"
    }
    if ([string]::IsNullOrWhiteSpace($manifest.requiredUvVersion)) {
        throw "Manifest requiredUvVersion is empty"
    }
    if (@($manifest.pythonVersions).Count -eq 0) {
        throw "Manifest pythonVersions is empty"
    }
    if (@($manifest.repositories).Count -eq 0) {
        throw "Manifest repositories is empty"
    }

    $names = @($manifest.repositories | ForEach-Object { $_.name })
    if (@($names | Sort-Object -Unique).Count -ne $names.Count) {
        throw "Manifest repository names must be unique"
    }
    foreach ($entry in $manifest.repositories) {
        foreach ($field in @("name", "path", "source")) {
            if ([string]::IsNullOrWhiteSpace($entry.$field)) {
                throw "Repository entry is missing '$field'"
            }
        }
        if (@($entry.pytestArgs).Count -eq 0) {
            throw "Repository '$($entry.name)' has no pytestArgs"
        }
    }
    return [pscustomobject]@{ Path = $fullPath; Data = $manifest }
}

function Resolve-UvCommand {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $uv) {
        return [pscustomobject]@{ Command = $uv.Source; Prefix = @() }
    }

    foreach ($pythonName in @("python", "py")) {
        $python = Get-Command $pythonName -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            continue
        }
        & $python.Source -m uv --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ Command = $python.Source; Prefix = @("-m", "uv") }
        }
    }
    throw "uv was not found. Install the version required by config/repositories.json."
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory)]$Uv,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $allArguments = @($Uv.Prefix) + $Arguments
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Uv.Command @allArguments | Out-Host
        $exitCode = $LASTEXITCODE
        return [int]$exitCode
    }
    finally {
        Pop-Location
    }
}

function Add-Result {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$Results,
        [Parameter(Mandatory)][string]$RepositoryName,
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$Check,
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][double]$Seconds,
        [string]$Note = ""
    )

    $Results.Add([pscustomobject]@{
        Repository = $RepositoryName
        Python = $Python
        Check = $Check
        Status = $Status
        Seconds = [math]::Round($Seconds, 2)
        Note = $Note
    })
}

$manifestResult = Read-RepositoryManifest -Path $ManifestPath
$manifest = $manifestResult.Data
$manifestDirectory = Split-Path -Parent $manifestResult.Path
$metaRoot = Resolve-FullPath -Path ".." -BasePath $manifestDirectory
$workspaceRoot = Resolve-FullPath -Path $manifest.workspaceRoot -BasePath $metaRoot
$selected = @($manifest.repositories)

if ($Repository.Count -gt 0) {
    $unknown = @($Repository | Where-Object { $_ -notin @($selected.name) })
    if ($unknown.Count -gt 0) {
        throw "Unknown repository selection: $($unknown -join ', ')"
    }
    $selected = @($selected | Where-Object { $_.name -in $Repository })
}

$versions = if ($PythonVersion.Count -gt 0) { @($PythonVersion) } else { @($manifest.pythonVersions) }
foreach ($version in $versions) {
    if ($version -notmatch '^3\.(11|14)$') {
        throw "Unsupported Python version '$version'; expected 3.11 or 3.14"
    }
}

if ($ValidateOnly) {
    Write-Host "Manifest OK: $($selected.Count) repositories; Python $($versions -join ', '); uv $($manifest.requiredUvVersion)."
    $syncPlan = if ($SkipSync) { "no-sync" } else { "sync" }
    foreach ($entry in $selected) {
        Write-Host "PLAN $($entry.name): lock, $syncPlan, lint, format-check, mypy, bandit, pytest, build"
    }
    exit 0
}

$uv = Resolve-UvCommand
$versionOutput = & $uv.Command @($uv.Prefix) --version
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "uv $([regex]::Escape($manifest.requiredUvVersion))\b") {
    throw "Expected uv $($manifest.requiredUvVersion), got: $versionOutput"
}

$results = [System.Collections.Generic.List[object]]::new()
$stopRequested = $false

foreach ($entry in $selected) {
    if ($stopRequested) { break }
    $repoPath = Resolve-FullPath -Path $entry.path -BasePath $workspaceRoot
    $workspacePrefix = $workspaceRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $repoPath.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Repository path escapes workspace root: $repoPath"
    }

    $requiredFiles = @(".git", "pyproject.toml", "uv.lock", ".python-version", $entry.source, "tests")
    $missing = @($requiredFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $repoPath $_)) })
    if ($missing.Count -gt 0) {
        Add-Result -Results $results -RepositoryName $entry.name -Python "-" -Check "preflight" -Status "FAIL" -Seconds 0 -Note "missing: $($missing -join ', ')"
        if ($FailFast) { $stopRequested = $true }
        continue
    }

    $dirtyCount = @(& git -C $repoPath status --porcelain).Count
    $dirtyNote = if ($dirtyCount -gt 0) { "dirty files preserved: $dirtyCount" } else { "clean" }
    Write-Host "`n=== $($entry.name) ($dirtyNote) ===" -ForegroundColor Cyan

    $lockWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $lockExit = Invoke-Uv -Uv $uv -WorkingDirectory $repoPath -Arguments @("lock", "--check")
    $lockWatch.Stop()
    Add-Result -Results $results -RepositoryName $entry.name -Python "-" -Check "lock" -Status $(if ($lockExit -eq 0) { "PASS" } else { "FAIL" }) -Seconds $lockWatch.Elapsed.TotalSeconds -Note $dirtyNote
    if ($lockExit -ne 0 -and $FailFast) { $stopRequested = $true; continue }

    foreach ($version in $versions) {
        if ($stopRequested) { break }
        $checks = [System.Collections.Generic.List[object]]::new()
        $runArguments = @("run", "--python", $version, "--locked")
        if (-not $SkipSync) {
            $checks.Add([pscustomobject]@{ Name = "sync"; Args = @("sync", "--python", $version, "--locked") })
        }
        else {
            $runArguments += "--no-sync"
        }
        $checks.Add([pscustomobject]@{ Name = "lint"; Args = $runArguments + @("ruff", "check", $entry.source, "tests") })
        $checks.Add([pscustomobject]@{ Name = "format"; Args = $runArguments + @("ruff", "format", "--check", $entry.source, "tests") })
        $checks.Add([pscustomobject]@{ Name = "mypy"; Args = $runArguments + @("mypy", $entry.source) })
        $checks.Add([pscustomobject]@{ Name = "bandit"; Args = $runArguments + @("bandit", "-q", "-r", $entry.source, "-x", "tests") })
        $checks.Add([pscustomobject]@{ Name = "pytest"; Args = $runArguments + @("pytest") + @($entry.pytestArgs) })
        $checks.Add([pscustomobject]@{ Name = "build"; Args = @("build", "--python", $version, "--no-sources") })

        foreach ($check in $checks) {
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $exitCode = Invoke-Uv -Uv $uv -WorkingDirectory $repoPath -Arguments $check.Args
            $watch.Stop()
            $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
            Add-Result -Results $results -RepositoryName $entry.name -Python $version -Check $check.Name -Status $status -Seconds $watch.Elapsed.TotalSeconds
            if ($exitCode -ne 0 -and $FailFast) {
                $stopRequested = $true
                break
            }
        }
    }
}

Write-Host "`n=== Kairos local verification summary ===" -ForegroundColor Cyan
$results | Format-Table Repository, Python, Check, Status, Seconds, Note -AutoSize
$failed = @($results | Where-Object { $_.Status -eq "FAIL" })
Write-Host ("Passed: {0}; failed: {1}; total: {2}" -f ($results.Count - $failed.Count), $failed.Count, $results.Count)
if ($failed.Count -gt 0) { exit 1 }
exit 0
