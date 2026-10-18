[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'Kairos-R7-SQL-TechnicalAlerts-V1-20261016'
$launcher = Join-Path $PSScriptRoot 'Run-HiddenPowerShell.vbs'
$hostPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$task = Get-ScheduledTask -TaskName $taskName
$actions = @($task.Actions)
if ($actions.Count -ne 1) { throw 'EXPECTED_SINGLE_ALERT_ACTION_REQUIRED' }
$oldAction = $actions[0]
if ($oldAction.Execute -eq $hostPath -and $oldAction.Arguments.StartsWith('//B //NoLogo "' + $launcher + '" ')) {
    [ordered]@{ status = 'ALREADY_HIDDEN'; task = $taskName } | ConvertTo-Json -Compress
    exit 0
}

# Preserve the existing poll command byte for byte. Do not initialize journals,
# reinstall the monitor, change credentials, dispatch it, or alter its schedule.
$prefix = '-NoProfile -NonInteractive -WindowStyle Hidden -Command "'
if ($oldAction.Execute -ne $powershellPath -or
    -not $oldAction.Arguments.StartsWith($prefix) -or
    -not $oldAction.Arguments.EndsWith('"') -or
    $oldAction.WorkingDirectory -ne 'D:\Kairos\kairos') {
    throw 'EXISTING_R7_SQL_POWERSHELL_ACTION_REQUIRED'
}
$command = $oldAction.Arguments.Substring($prefix.Length, $oldAction.Arguments.Length - $prefix.Length - 1)
if (-not $command.Contains('runtime_status_r7_notifier.py') -or
    -not $command.Contains("--poll-once --armed --profile 'r7-sql'")) {
    throw 'EXISTING_R7_SQL_POLL_REQUIRED'
}
foreach ($path in @($launcher, $hostPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'HIDDEN_LAUNCHER_REQUIRED' }
}
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$arguments = '//B //NoLogo "' + $launcher + '" ' + $encoded
$action = New-ScheduledTaskAction -Execute $hostPath -Argument $arguments -WorkingDirectory $oldAction.WorkingDirectory
if (-not $Execute) {
    [ordered]@{ status = 'PLAN_ONLY'; task = $taskName; poll_command_preserved = $true; interval_changed = $false } | ConvertTo-Json -Compress
    exit 0
}

if (Test-Path -LiteralPath $BackupDirectory) { throw 'NEW_BACKUP_DIRECTORY_REQUIRED' }
New-Item -ItemType Directory -Path $BackupDirectory | Out-Null
$beforeXml = Export-ScheduledTask -TaskName $taskName
$beforeXml | Set-Content -LiteralPath (Join-Path $BackupDirectory 'task-before.xml') -Encoding Unicode
Get-FileHash -LiteralPath $launcher -Algorithm SHA256 |
    Select-Object Path, Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BackupDirectory 'launcher-sha256.json') -Encoding UTF8
try {
    Set-ScheduledTask -TaskName $taskName -Action $action | Out-Null
    $afterXml = Export-ScheduledTask -TaskName $taskName
    $before = [xml]$beforeXml
    $after = [xml]$afterXml
    foreach ($node in @('RegistrationInfo', 'Triggers', 'Principals', 'Settings')) {
        if ($before.Task.$node.OuterXml -cne $after.Task.$node.OuterXml) { throw 'UNRELATED_TASK_SETTING_CHANGED' }
    }
    $installed = (Get-ScheduledTask -TaskName $taskName).Actions
    if ($installed.Execute -ne $hostPath -or $installed.Arguments -cne $arguments -or
        $installed.WorkingDirectory -cne $oldAction.WorkingDirectory) { throw 'HIDDEN_ACTION_NOT_INSTALLED' }
    $afterXml | Set-Content -LiteralPath (Join-Path $BackupDirectory 'task-after.xml') -Encoding Unicode
}
catch {
    Set-ScheduledTask -TaskName $taskName -Action $oldAction | Out-Null
    throw
}
[ordered]@{
    status = 'HIDDEN_ACTION_INSTALLED'
    task = $taskName
    poll_command_preserved = $true
    schedule_and_settings_preserved = $true
    task_started = $false
} | ConvertTo-Json -Compress
