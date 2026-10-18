# Hidden R7 SQL status checks on Windows

`-WindowStyle Hidden` alone can briefly open Windows Terminal before PowerShell
hides its console. The existing interactive scheduled task now uses
`wscript.exe` (a GUI executable) and `Run-HiddenPowerShell.vbs` to set the hidden
window state when PowerShell is created. The wrapper waits for PowerShell and
returns its exit code to Task Scheduler.

The repair converts the existing PowerShell command to UTF-16 Base64 for
`-EncodedCommand` without changing the command. It changes only the task action;
the two-minute timer, logon trigger, account, limits, notification behavior and
protected monitor sources remain as configured. It neither initializes journals
nor runs the task during installation.

Preview, then apply to the existing R7 SQL task:

```powershell
& D:\Kairos\kairos\development\ops_alerts\Repair-R7RuntimeAlertTaskVisibility.ps1 `
    -BackupDirectory D:\Kairos\runtime\console-visibility-20261018
& D:\Kairos\kairos\development\ops_alerts\Repair-R7RuntimeAlertTaskVisibility.ps1 `
    -BackupDirectory D:\Kairos\runtime\console-visibility-20261018 -Execute
```

Use a new backup directory for a future repair. An already repaired action is a
no-op. Installation saves the before/after task XML and launcher SHA-256. Verify
an actual scheduled run, successful `LastTaskResult`, and absence of visible
console windows; a zero result from a separate launcher smoke check alone does
not establish monitor health.

To restore the original action while preserving the current task settings:

```powershell
$original = [xml](Get-Content -Raw -LiteralPath D:\Kairos\runtime\console-visibility-20261018\task-before.xml)
$exec = $original.Task.Actions.Exec
$action = New-ScheduledTaskAction -Execute $exec.Command `
    -Argument $exec.Arguments -WorkingDirectory $exec.WorkingDirectory
Set-ScheduledTask -TaskName Kairos-R7-SQL-TechnicalAlerts-V1-20261016 -Action $action
```

The existing installer creates a fresh protected monitoring journal and requires
the task to be absent. Do not rerun it to repair an already active task. This
visibility repair intentionally leaves that byte-checked installer unchanged.
