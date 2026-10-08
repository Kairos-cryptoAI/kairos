function Invoke-ReleaseGit {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    # Git can emit benign warnings for ignored, inaccessible cache directories. The
    # release decision is based on its exit status and stdout, so do not let an
    # external-program stderr record become a PowerShell terminating error.
    $result = & git -C $RepositoryPath @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git -C $RepositoryPath $($Arguments -join ' ') failed: $($result -join [Environment]::NewLine)"
    }
    return ($result | Out-String).Trim()
}

function Assert-ReleaseRepositoryCheckout {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryPath,
        [Parameter(Mandatory = $true)][string]$RepositoryName,
        [Parameter(Mandatory = $true)][string]$ExpectedOrigin
    )

    $origin = Invoke-ReleaseGit -RepositoryPath $RepositoryPath -Arguments @("remote", "get-url", "origin")
    if ($origin -cne $ExpectedOrigin) {
        throw "$RepositoryName origin URL does not match the current-release manifest"
    }

    # Include non-ignored untracked files in the checkout cleanliness check.
    # `normal` reports an untracked directory once without enumerating its contents.
    $dirty = Invoke-ReleaseGit -RepositoryPath $RepositoryPath -Arguments @(
        "status", "--porcelain=v1", "--untracked-files=normal"
    )
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "$RepositoryName has uncommitted changes or untracked files"
    }
}
