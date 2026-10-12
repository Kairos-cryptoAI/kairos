[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Read-only interpreter/path probe in the actual Limited scheduler context.
# There is no notifier import, credential read, database, queue or HTTP call.
$resultPath = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r4\python-host-probe.json'
$targets = [ordered]@{
    venv_home = 'C:\Users\loval\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
    physical_base = 'C:\Users\loval\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
    persistence_launcher = 'D:\Kairos\kairos-persistence\.venv\Scripts\python.exe'
}
$checks = [ordered]@{}
foreach ($name in $targets.Keys) {
    $target = $targets[$name]
    $present = Test-Path -LiteralPath $target -PathType Leaf
    $exitCode = $null
    $version = $null
    if ($present) {
        $versionOutput = & $target -B -E -s --version 2>$null
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0 -and $versionOutput -match '^Python [0-9]+\.[0-9]+\.[0-9]+$') {
            $version = [string]$versionOutput
        }
    }
    $checks[$name] = [ordered]@{ present = $present; exit_code = $exitCode; version = $version }
}
$report = [ordered]@{
    kind = 'kairos.notifications.limited-python-host-probe.v1'
    captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    checks = $checks
    credential_reads = 0
    network_calls = 0
    trading_authority = $false
}
$parent = Get-Item -LiteralPath (Split-Path -Parent $resultPath)
if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_REJECTED' }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed = @($sid, 'S-1-5-18', 'S-1-5-32-544')
$rules = (Get-Acl -LiteralPath $parent.FullName).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])
if (@($rules | Where-Object { $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -notin $allowed }).Count) {
    throw 'PRIVATE_PARENT_REQUIRED'
}
$encoded = [Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 5 -Compress) + "`n")
$stream = [IO.FileStream]::new($resultPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {
    $stream.Write($encoded,0,$encoded.Length)
    $stream.Flush($true)
} finally { $stream.Dispose() }
exit 0
