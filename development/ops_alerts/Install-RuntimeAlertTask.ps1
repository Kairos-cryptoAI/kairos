[CmdletBinding()]
param([switch]$Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$taskName = 'Kairos-R4-TechnicalAlerts-20261012'
$metaRoot = 'D:\Kairos\kairos'
$driverPath = Join-Path $metaRoot 'development\ops_alerts\runtime_status_notifier.py'
$pythonPath = 'D:\Kairos\kairos-persistence\.venv\Scripts\python.exe'
$acceptancePath = 'D:\Kairos\runtime\alert-delivery-20261012\operational-r4\owner-acceptance.json'
$gitPath = 'C:\Program Files\Git\cmd\git.exe'
$signer = '40AF365C6682B73D056A6A274DBFF6B65BE9F827'

if (-not $Execute) {
    [ordered]@{
        status = 'PLAN_ONLY'
        task = $taskName
        interval_seconds = 120
        monitoring = 'one fixed R4 status file only'
        trading_authority = $false
        database_or_queue_access = $false
    } | ConvertTo-Json -Compress
    exit 0
}

# This task is distinct from the runtime boot task. It never starts Docker,
# consumers, exchange processes, or a database. Every dispatch revalidates the
# signed driver, private operator acceptance and append-only delivery guards.
foreach ($path in @($driverPath, $pythonPath, $acceptancePath, $PSCommandPath)) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'REGULAR_LOCAL_FILE_REQUIRED'
    }
    $parent = $item.Directory
    while ($null -ne $parent) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'REPARSE_PATH_REJECTED'
        }
        $parent = $parent.Parent
    }
}
$metadata = & $gitPath -C $metaRoot show -s '--format=%H %G? %GF' HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or $metadata -notmatch ('^[0-9a-f]{40} G ' + $signer + '$')) {
    throw 'TRUSTED_SIGNED_HEAD_REQUIRED'
}
$branch = & $gitPath -C $metaRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'MAIN_REQUIRED' }
$changes = & $gitPath -C $metaRoot status --porcelain --untracked-files=normal -- `
    development/ops_alerts/runtime_status_notifier.py `
    development/ops_alerts/Install-RuntimeAlertTask.ps1
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'COMMITTED_TASK_SOURCES_REQUIRED' }

$acceptanceItem = Get-Item -LiteralPath $acceptancePath
if ($acceptanceItem.Length -gt 16384) { throw 'BOUNDED_ACCEPTANCE_REQUIRED' }
$acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json
if ($acceptance.human_acknowledged -ne $true -or
    $acceptance.chat_id -ne -1004475802889 -or
    $acceptance.trading_authority -ne $false) {
    throw 'CURRENT_RECIPIENT_ACCEPTANCE_REQUIRED'
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'EXISTING_NOTIFICATION_TASK_REQUIRES_REVIEW'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$hiddenShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$pollCommand = "& 'D:\Kairos\kairos-persistence\.venv\Scripts\python.exe' -B -E -s 'D:\Kairos\kairos\development\ops_alerts\runtime_status_notifier.py' --poll-once --armed; exit " + '$LASTEXITCODE'
$action = New-ScheduledTaskAction -Execute $hiddenShell `
    -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -Command "' + $pollCommand + '"') `
    -WorkingDirectory $metaRoot
$timer = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
    -RepetitionInterval ([TimeSpan]::FromMinutes(2))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$definition = New-ScheduledTask -Action $action -Trigger @($timer, $logon) `
    -Principal $principal -Settings $settings `
    -Description 'Kairos R4: private status-file-only technical alerts; no trading, DB or queue authority.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition | Out-Null

# Registration only: a separate observed dispatch is required for acceptance.
[ordered]@{
    status = 'REGISTERED_NOT_YET_DISPATCH_VERIFIED'
    task = $taskName
    interval_seconds = 120
    hidden = $true
    run_level = 'Limited'
    multiple_instances = 'IgnoreNew'
    source_revision = ($metadata -split ' ')[0]
    installer_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    driver_sha256 = (Get-FileHash -LiteralPath $driverPath -Algorithm SHA256).Hash.ToLowerInvariant()
    acceptance_sha256 = (Get-FileHash -LiteralPath $acceptancePath -Algorithm SHA256).Hash.ToLowerInvariant()
    trading_authority = $false
} | ConvertTo-Json -Compress
