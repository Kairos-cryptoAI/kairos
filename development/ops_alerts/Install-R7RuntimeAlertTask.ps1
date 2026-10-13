[CmdletBinding()]
param([switch]$Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'Kairos-R7-TechnicalAlerts-V1-20261013'
$metaRoot = 'D:\Kairos\kairos'
$privateRoot = 'D:\Kairos\runtime\alert-delivery-20261013\operational-r7'
$driverPath = Join-Path $metaRoot 'development\ops_alerts\runtime_status_r7_notifier.py'
$pythonPath = 'C:\Users\loval\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
$gitPath = 'C:\Program Files\Git\cmd\git.exe'
$signer = '40AF365C6682B73D056A6A274DBFF6B65BE9F827'
$relativeFiles = @(
    'development/ops_alerts/runtime_status_r7_notifier.py',
    'development/ops_alerts/test_runtime_status_r7_notifier.py',
    'development/ops_alerts/Install-R7RuntimeAlertTask.ps1',
    'development/ops_alerts/runtime_status_r5_notifier.py'
)

if (-not $Execute) {
    [ordered]@{
        status = 'PLAN_ONLY'
        task = $taskName
        interval_seconds = 120
        protected_status_file_only = $true
        database_or_queue_access = $false
        trading_authority = $false
        task_started = $false
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
$revision = ($metadata -split ' ')[0]
$branch = & $gitPath -C $metaRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'MAIN_REQUIRED' }
$origin = & $gitPath -C $metaRoot rev-parse origin/main
if ($LASTEXITCODE -ne 0 -or $origin -ne $revision) { throw 'SIGNED_ORIGIN_HEAD_REQUIRED' }
foreach ($relative in $relativeFiles) {
    $sourcePath = Join-Path $metaRoot ($relative -replace '/', '\')
    $item = Get-Item -LiteralPath $sourcePath -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'REGULAR_LOCAL_FILE_REQUIRED' }
    $committedBlob = & $gitPath -C $metaRoot rev-parse ($revision + ':' + $relative)
    if ($LASTEXITCODE -ne 0) { throw 'COMMITTED_R7_SOURCES_REQUIRED' }
    $localBlob = & $gitPath -C $metaRoot hash-object --no-filters -- $sourcePath
    if ($LASTEXITCODE -ne 0 -or $localBlob -ne $committedBlob) { throw 'R7_SOURCE_BYTES_MISMATCH' }
}
$changes = & $gitPath -C $metaRoot status --porcelain --untracked-files=normal -- $relativeFiles
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'COMMITTED_R7_SOURCES_REQUIRED' }
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'PINNED_PYTHON_REQUIRED' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'NEW_R7_TASK_MUST_BE_ABSENT' }

# Create a new isolated owner/Admin/SYSTEM-only journal directory. Never reuse
# the R5/R6 roots or modify their bindings, journals, or scheduled tasks.
if (Test-Path -LiteralPath $privateRoot) { throw 'NEW_R7_PRIVATE_ROOT_MUST_BE_ABSENT' }
$parentRoot = Split-Path -Parent $privateRoot
$probe = Get-Item -LiteralPath (Split-Path -Parent $parentRoot) -Force
while ($null -ne $probe) {
    if ($probe.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_PATH_REJECTED' }
    $probe = $probe.Parent
}
if (Test-Path -LiteralPath $parentRoot) {
    $parentItem = Get-Item -LiteralPath $parentRoot -Force
    if ($parentItem.PSIsContainer -eq $false -or ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'PRIVATE_PARENT_REJECTED' }
}
if (-not (Test-Path -LiteralPath $parentRoot)) {
    New-Item -ItemType Directory -Path $parentRoot | Out-Null
}
New-Item -ItemType Directory -Path $privateRoot | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner($identity.User)
foreach ($sidText in @($identity.User.Value, 'S-1-5-18', 'S-1-5-32-544')) {
    $sid = New-Object Security.Principal.SecurityIdentifier($sidText)
    $rule = New-Object -TypeName Security.AccessControl.FileSystemAccessRule -ArgumentList @(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $privateRoot -AclObject $acl

# Admission and the initial quiet baseline are read-only except for the new
# R7 binding/journal. No credential is loaded and no message is sent here.
& $pythonPath -B -E -s $driverPath --initialize --armed
if ($LASTEXITCODE -ne 0) { throw 'R7_ACCEPTED_RECEIPT_OR_QUIET_STATUS_REQUIRED' }

$identityName = $identity.Name
$pollCommand = "& '" + $pythonPath + "' -B -E -s '" + $driverPath + "' --poll-once --armed; exit " + '$LASTEXITCODE'
$action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -Command "' + $pollCommand + '"') -WorkingDirectory $metaRoot
$timer = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) -RepetitionInterval ([TimeSpan]::FromMinutes(2))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identityName
$principal = New-ScheduledTaskPrincipal -UserId $identityName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$definition = New-ScheduledTask -Action $action -Trigger @($timer, $logon) -Principal $principal -Settings $settings -Description 'Kairos R7: private status-file-only technical alerts; no trading, DB or queue authority.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition | Out-Null
[ordered]@{
    status = 'REGISTERED_NOT_YET_DISPATCH_VERIFIED'
    task = $taskName
    interval_seconds = 120
    hidden = $true
    run_level = 'Limited'
    task_started = $false
    trading_authority = $false
} | ConvertTo-Json -Compress
