[CmdletBinding()]
param([switch]$Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'Kairos-R5-TechnicalAlerts-20261012'
$oldTaskName = 'Kairos-R4-TechnicalAlerts-20261012'
$metaRoot = 'D:\Kairos\kairos'
$privateRoot = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r5'
$driverPath = Join-Path $metaRoot 'development\ops_alerts\runtime_status_r5_notifier.py'
$pythonPath = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r4\notification-env\Scripts\python.exe'
$gitPath = 'C:\Program Files\Git\cmd\git.exe'
$signer = '40AF365C6682B73D056A6A274DBFF6B65BE9F827'
if (-not $Execute) {
    [ordered]@{ status='PLAN_ONLY'; task=$taskName; interval_seconds=120; database_or_queue_access=$false; trading_authority=$false } | ConvertTo-Json -Compress
    exit 0
}
foreach ($path in @($driverPath, $pythonPath, $PSCommandPath, (Join-Path $privateRoot 'binding.json'), (Join-Path $privateRoot 'binding.json.asc'), (Join-Path $privateRoot 'events.jsonl'))) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'REGULAR_LOCAL_FILE_REQUIRED' }
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
$changes = & $gitPath -C $metaRoot status --porcelain --untracked-files=normal -- development/ops_alerts/runtime_status_r5_notifier.py development/ops_alerts/Install-R5RuntimeAlertTask.ps1
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'COMMITTED_TASK_SOURCES_REQUIRED' }
& $pythonPath -B -E -s $driverPath --verify-only --armed
if ($LASTEXITCODE -ne 0) { throw 'R5_SIGNED_BINDING_ADMISSION_REQUIRED' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'NEW_R5_TASK_MUST_BE_ABSENT' }
$oldTask = Get-ScheduledTask -TaskName $oldTaskName -ErrorAction SilentlyContinue
if ($oldTask -and ($oldTask.State -eq 'Running' -or
    $oldTask.Description -ne 'Kairos R4: private status-file-only technical alerts; no trading, DB or queue authority.' -or
    @($oldTask.Actions).Count -ne 1 -or
    $oldTask.Actions[0].Execute -ne 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -or
    $oldTask.Actions[0].Arguments -notlike '*operational-r4\notification-env\Scripts\python.exe*runtime_status_notifier.py*--poll-once --armed*' -or
    $oldTask.Settings.Hidden -ne $true -or $oldTask.Principal.RunLevel.ToString() -ne 'Limited')) { throw 'OLD_R4_TASK_REVIEW_REQUIRED' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$pollCommand = "& '" + $pythonPath + "' -B -E -s '" + $driverPath + "' --poll-once --armed; exit " + '$LASTEXITCODE'
$action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -Command "' + $pollCommand + '"') -WorkingDirectory $metaRoot
$timer = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) -RepetitionInterval ([TimeSpan]::FromMinutes(2))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$definition = New-ScheduledTask -Action $action -Trigger @($timer,$logon) -Principal $principal -Settings $settings -Description 'Kairos R5: private status-file-only technical alerts; no trading, DB or queue authority.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition | Out-Null
if ($oldTask) {
    # Keep its definition, journal and acceptance. Only its obsolete schedule is disabled.
    Disable-ScheduledTask -TaskName $oldTaskName | Out-Null
}
[ordered]@{status='REGISTERED_NOT_YET_DISPATCH_VERIFIED'; task=$taskName; obsolete_r4_schedule_disabled=[bool]$oldTask; interval_seconds=120; hidden=$true; run_level='Limited'; trading_authority=$false} | ConvertTo-Json -Compress
