[CmdletBinding()]
param([switch]$Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'Kairos-R6-TechnicalAlerts-V3-20261012'
$metaRoot = 'D:\Kairos\kairos'
$privateRoot = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r6'
$driverPath = Join-Path $metaRoot 'development\ops_alerts\runtime_status_r6_notifier.py'
$pythonPath = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r4\notification-env\Scripts\python.exe'
$gitPath = 'C:\Program Files\Git\cmd\git.exe'
$signer = '40AF365C6682B73D056A6A274DBFF6B65BE9F827'

if (-not $Execute) {
    [ordered]@{
        status = 'PLAN_ONLY'
        task = $taskName
        interval_seconds = 120
        creates_healthy_baseline_after_route_qualification = $true
        database_or_queue_access = $false
        trading_authority = $false
    } | ConvertTo-Json -Compress
    exit 0
}

foreach ($path in @($driverPath, $pythonPath, $PSCommandPath)) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'REGULAR_LOCAL_FILE_REQUIRED'
    }
    $parent = $item.Directory
    while ($null -ne $parent) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_PATH_REJECTED' }
        $parent = $parent.Parent
    }
}

$metadata = & $gitPath -C $metaRoot show -s '--format=%H %G? %GF' HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or $metadata -notmatch ('^[0-9a-f]{40} G ' + $signer + '$')) { throw 'TRUSTED_SIGNED_HEAD_REQUIRED' }
$branch = & $gitPath -C $metaRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'MAIN_REQUIRED' }
$origin = & $gitPath -C $metaRoot rev-parse origin/main
if ($LASTEXITCODE -ne 0 -or $origin -ne ($metadata -split ' ')[0]) { throw 'SIGNED_ORIGIN_HEAD_REQUIRED' }
$changes = & $gitPath -C $metaRoot status --porcelain --untracked-files=normal -- development/ops_alerts/runtime_status_r6_notifier.py development/ops_alerts/test_runtime_status_r6_notifier.py development/ops_alerts/Install-R6RuntimeAlertTask.ps1
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'COMMITTED_R6_SOURCES_REQUIRED' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'NEW_R6_TASK_MUST_BE_ABSENT' }

# This performs source admission, requires the accepted R6 route receipt, and
# creates only the healthy R6 baseline. It does not read a token or send.
& $pythonPath -B -E -s $driverPath --initialize --armed
if ($LASTEXITCODE -ne 0) { throw 'R6_BASELINE_OR_SIGNED_BINDING_REQUIRED' }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$pollCommand = "& '" + $pythonPath + "' -B -E -s '" + $driverPath + "' --poll-once --armed; exit " + '$LASTEXITCODE'
$action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -Command "' + $pollCommand + '"') -WorkingDirectory $metaRoot
$timer = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) -RepetitionInterval ([TimeSpan]::FromMinutes(2))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$definition = New-ScheduledTask -Action $action -Trigger @($timer, $logon) -Principal $principal -Settings $settings -Description 'Kairos R6 V3: private status-file-only alerts after one-shot route qualification; no trading, DB or queue authority.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition | Out-Null
[ordered]@{
    status = 'REGISTERED_NOT_YET_DISPATCH_VERIFIED'
    task = $taskName
    interval_seconds = 120
    hidden = $true
    run_level = 'Limited'
    prior_r5_unknown_retained = $true
    trading_authority = $false
} | ConvertTo-Json -Compress
