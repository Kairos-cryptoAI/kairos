[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $repoRoot "scripts\ReleaseCheckoutIdentity.ps1")

$temporaryBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$temporaryRoot = [System.IO.Path]::GetFullPath((Join-Path $temporaryBase ("kairos-release-checkout-" + [guid]::NewGuid().ToString("N"))))
$repositoryPath = Join-Path $temporaryRoot "repo"
$expectedOrigin = "https://github.com/Kairos-cryptoAI/release-checkout-test.git"

function Invoke-TestGit {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = & git -C $repositoryPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Test git command failed: git -C $repositoryPath $($Arguments -join ' '): $output"
    }
    return $output
}

function Assert-ThrowsContaining {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$ExpectedText
    )

    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message.Contains($ExpectedText)) { return }
        throw
    }
    throw "Expected an error containing '$ExpectedText'"
}

try {
    $null = New-Item -ItemType Directory -Path $repositoryPath -Force
    $initOutput = & git init --quiet --initial-branch=main $repositoryPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Unable to initialize temporary test repository: $initOutput" }
    $null = Invoke-TestGit -Arguments @("remote", "add", "origin", $expectedOrigin)

    # Ignored local files are intentionally outside the source identity.
    $excludePath = Join-Path $repositoryPath ".git\info\exclude"
    [System.IO.File]::AppendAllText($excludePath, ".ignored/`n", [System.Text.Encoding]::ASCII)
    $null = New-Item -ItemType Directory -Path (Join-Path $repositoryPath ".ignored") -Force
    Set-Content -LiteralPath (Join-Path $repositoryPath ".ignored\cache.bin") -Value "fixture" -NoNewline
    Assert-ReleaseRepositoryCheckout -RepositoryPath $repositoryPath -RepositoryName "fixture" -ExpectedOrigin $expectedOrigin

    # Non-ignored untracked files must block source certification.
    Set-Content -LiteralPath (Join-Path $repositoryPath "untracked.txt") -Value "fixture" -NoNewline
    Assert-ThrowsContaining -ExpectedText "untracked files" -Action {
        Assert-ReleaseRepositoryCheckout -RepositoryPath $repositoryPath -RepositoryName "fixture" -ExpectedOrigin $expectedOrigin
    }
    Remove-Item -LiteralPath (Join-Path $repositoryPath "untracked.txt")

    # The configured origin must match the manifest before origin/main is trusted.
    $wrongOrigin = "https://github.com/example/fork.git"
    $null = Invoke-TestGit -Arguments @("remote", "set-url", "origin", $wrongOrigin)
    Assert-ThrowsContaining -ExpectedText "origin URL does not match" -Action {
        Assert-ReleaseRepositoryCheckout -RepositoryPath $repositoryPath -RepositoryName "fixture" -ExpectedOrigin $expectedOrigin
    }

    # Exercise real native stderr under Windows PowerShell 5.1 as well as pwsh.
    # Only this script's Git alias is replaced; the fixture never mutates files.
    $priorGitAlias = Get-Alias -Name git -ErrorAction SilentlyContinue
    $priorNativeErrorPreference = Get-Variable -Name "PSNativeCommandUseErrorActionPreference" -ErrorAction SilentlyContinue
    try {
        if ($null -ne $priorNativeErrorPreference) {
            $savedNativeErrorPreference = $priorNativeErrorPreference.Value
            Set-Variable -Name "PSNativeCommandUseErrorActionPreference" -Value $true -Scope Script
        }
        Set-Alias -Name git -Value (Join-Path $PSScriptRoot "fixtures\release-git-warning.cmd") -Scope Script
        $output = Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("warning")
        if ($output -cne "synthetic release Git output") {
            throw "A successful Git command with stderr lost its exact stdout"
        }
        Assert-ThrowsContaining -ExpectedText "exit code 37" -Action {
            Invoke-ReleaseGit -RepositoryPath $repositoryPath -Arguments @("nonzero")
        }
        if ($ErrorActionPreference -ne "Stop") {
            throw "Git verification leaked its temporary error preference"
        }
        if ($null -ne $priorNativeErrorPreference -and $PSNativeCommandUseErrorActionPreference -ne $true) {
            throw "Git verification leaked its temporary native error preference"
        }
    }
    finally {
        if ($null -ne $priorNativeErrorPreference) {
            Set-Variable -Name "PSNativeCommandUseErrorActionPreference" -Value $savedNativeErrorPreference -Scope Script
        }
        if ($null -eq $priorGitAlias) {
            Remove-Item -LiteralPath Alias:\git
        }
        else {
            Set-Alias -Name git -Value $priorGitAlias.Definition -Scope Script
        }
    }

    Write-Host "Release checkout identity regression tests passed."
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot -PathType Container) {
        $resolvedTemporaryRoot = (Resolve-Path -LiteralPath $temporaryRoot).ProviderPath
        if ($resolvedTemporaryRoot -cne $temporaryRoot -or
            -not $resolvedTemporaryRoot.StartsWith($temporaryBase, [System.StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedTemporaryRoot) -notmatch '^kairos-release-checkout-[0-9a-f]{32}$') {
            throw "Refusing cleanup outside the exact disposable checkout fixture"
        }
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
