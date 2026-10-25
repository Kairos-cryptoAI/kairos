[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Receipt,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReceiptSha256,
    [Parameter(Mandatory)][string]$Signature,
    [Parameter(Mandatory)][string]$NewHostReportPath,
    [Parameter(Mandatory)][string]$PreviousHostReport,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$PreviousHostReportSha256,
    [switch]$Execute
)

# Additive, reviewed V2 registration for one exact CURRENT owner. This script
# never starts a task, mutates DB/Redis resources, or changes the old binding.
# Native read-only admission may create exact-owner inspection evidence.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try { $PSNativeCommandUseErrorActionPreference = $false } catch { }

$Owner = '8ed2564832624471a693726a35917416'
$DeployRevision = 'bfcfd18a1edbf2b54bebfb2c477b7883655435b6'
$DeployRoot = 'D:\Kairos\kairos-deploy'
$MetaRoot = 'D:\Kairos\kairos'
$RuntimeRoot = 'D:\Kairos\runtime\current-runtime-20261024'
$InputsRoot = 'D:\Kairos\runtime\prod-runtime-inputs-20261024'
$OldAcceptanceId = '30be2a32327948a39b337bc01f4b8b86'
$OldReportSha = 'de4e02ca34833341bd716524bf9b2527a274a8e4a9c428a2db3dde0ff0547c39'
$OldFailureSha = '9e63ae25d44bde0128c72b7e8177d26c112c38de71af7bfc162b05f28fde766e'
$OldBindingSha = '4a59585b63cb640d538566129589d201d5925c24ec4647673b7ee6a2619dbbb1'
$TrustedSigner = '40AF365C6682B73D056A6A274DBFF6B65BE9F827'
$Git = 'C:\Program Files\Git\cmd\git.exe'
$Gpg = 'C:\Program Files\Git\usr\bin\gpg.exe'
$PythonPowerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$PythonPath = 'C:\Users\loval\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
$MetaRelative = 'development/ops_alerts/Register-CurrentReviewedBootTask.ps1'

function Stop-Safe([string]$Category) {
    throw $Category
}

function Invoke-GitText([string[]]$Arguments) {
    $output = & $Git -C $DeployRoot -c "gpg.program=$Gpg" @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { Stop-Safe 'SIGNED_DEPLOY_SOURCE_REQUIRED' }
    return (($output -join "`n").Trim())
}

function Assert-RegularFile([string]$Path, [long]$Maximum = 1048576) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt $Maximum) {
        Stop-Safe 'BOUNDED_REGULAR_FILE_REQUIRED'
    }
    return $item.FullName
}

function Read-BoundedJson([string]$Path, [long]$Maximum = 1048576) {
    $full = Assert-RegularFile $Path $Maximum
    $raw = [IO.File]::ReadAllBytes($full)
    if ($raw.Length -gt $Maximum) { Stop-Safe 'BOUNDED_JSON_REQUIRED' }
    try { return ([Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json -ErrorAction Stop) }
    catch { Stop-Safe 'BOUNDED_JSON_REQUIRED' }
}

function Write-NewBytes([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

function New-PrivateDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { Stop-Safe 'EXISTING_REVIEW_WORK_REQUIRES_INSPECTION' }
    $null = New-Item -ItemType Directory -Path $Path
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User)
    $ids = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User,
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    foreach ($sid in $ids) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    $saved = Get-Acl -LiteralPath $Path
    if (-not $saved.AreAccessRulesProtected -or $saved.Access.Count -ne 3) {
        Stop-Safe 'REVIEW_WORK_PRIVATE_ACL_REQUIRED'
    }
}

function Get-Bootstrap([string]$Template, [string]$BindingPath, [string]$BindingHash) {
    $pathToken = @'
$($bindingPath.Replace('\','/'))
'@
    $pathToken = $pathToken.Trim()
    $hashToken = @'
$bindingHash
'@
    $hashToken = $hashToken.Trim()
    if ([regex]::Matches($Template, [regex]::Escape($pathToken)).Count -ne 1 -or
        [regex]::Matches($Template, [regex]::Escape($hashToken)).Count -ne 1) {
        Stop-Safe 'SIGNED_STOCK_BOOTSTRAP_TEMPLATE_CHANGED'
    }
    $result = $Template.Replace($pathToken, $BindingPath.Replace('\', '/')).Replace($hashToken, $BindingHash)
    if ($result.Contains('$') -or $result.Contains('"')) { Stop-Safe 'BOOTSTRAP_INTERPOLATION_UNRESOLVED' }
    return $result
}

function Assert-TrustedReceiptSignature([string]$Path, [string]$Sha256, [string]$Python) {
    $signaturePath = $Path + '.asc'
    $code = "import pathlib,sys;sys.path.insert(0,r'$DeployRoot');from scripts import runtime_epoch_current_boot as b;b.verify_receipt_signature(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),sys.argv[3]);print('SIGNATURE_OK')"
    $out = & $Python -I -B -c $code $Path $signaturePath $Sha256 2>$null
    if ($LASTEXITCODE -ne 0 -or (($out -join '').Trim() -cne 'SIGNATURE_OK')) {
        Stop-Safe 'TRUSTED_RECEIPT_SIGNATURE_REQUIRED'
    }
}

function Get-IdentitySid([string]$Value) {
    if ($Value -cmatch '^S-1-[0-9-]+$') { return $Value }
    return ([Security.Principal.NTAccount]::new($Value)).Translate([Security.Principal.SecurityIdentifier]).Value
}

function Get-TaskInfo([string]$TaskName) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    return [pscustomobject]@{ Task = $task; Info = $info }
}

function Assert-LogonTaskXml([string]$XmlText, [string]$ExpectedUser) {
    try { [xml]$xml = $XmlText } catch { Stop-Safe 'EXACT_LOGON_TASK_XML_REQUIRED' }
    $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
    $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $triggers = $xml.SelectNodes('/t:Task/t:Triggers/t:LogonTrigger', $ns)
    $allTriggers = $xml.SelectNodes('/t:Task/t:Triggers/*', $ns)
    $delay = if ($triggers.Count -eq 1) { $triggers[0].SelectSingleNode('t:Delay', $ns) } else { $null }
    $user = if ($triggers.Count -eq 1) { $triggers[0].SelectSingleNode('t:UserId', $ns) } else { $null }
    if ($triggers.Count -ne 1 -or $allTriggers.Count -ne 1 -or
        $null -eq $delay -or $delay.InnerText -cne 'PT2M' -or
        $null -eq $user -or (Get-IdentitySid $user.InnerText) -cne (Get-IdentitySid $ExpectedUser)) {
        Stop-Safe 'EXACT_INTERACTIVE_LOGON_TRIGGER_REQUIRED'
    }
}

function Assert-TaskProjection($Task, [string]$TaskName, [string]$Pythonw, [string]$Arguments, [string]$WorkingDirectory, [string]$User) {
    if ($Task.TaskName -cne $TaskName -or $Task.State -notin @('Ready', 'Disabled') -or
        $Task.Actions.Count -ne 1 -or
        [IO.Path]::GetFullPath($Task.Actions[0].Execute) -ine [IO.Path]::GetFullPath($Pythonw) -or
        $Task.Actions[0].Arguments -cne $Arguments -or
        [IO.Path]::GetFullPath($Task.Actions[0].WorkingDirectory) -ine [IO.Path]::GetFullPath($WorkingDirectory) -or
        $Task.Settings.Hidden -ne $true -or
        [string]$Task.Settings.MultipleInstances -cne 'IgnoreNew' -or
        $Task.Settings.RestartCount -ne 0 -or
        $Task.Settings.StartWhenAvailable -ne $false -or
        ([Xml.XmlConvert]::ToTimeSpan([string]$Task.Settings.ExecutionTimeLimit)) -ne (New-TimeSpan -Minutes 155) -or
        (Get-IdentitySid $Task.Principal.UserId) -cne (Get-IdentitySid $User) -or
        [string]$Task.Principal.RunLevel -cne 'Highest' -or
        [string]$Task.Principal.LogonType -cne 'Interactive') {
        Stop-Safe 'EXACT_CURRENT_TASK_PROJECTION_REQUIRED'
    }
    Assert-LogonTaskXml (Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop) $User
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Stop-Safe 'ELEVATED_READONLY_INVENTORY_REQUIRED'
    }

    $expectedHelperPath = [IO.Path]::GetFullPath((Join-Path $MetaRoot $MetaRelative))
    if ([IO.Path]::GetFullPath($PSCommandPath) -cne $expectedHelperPath) {
        Stop-Safe 'COMMITTED_META_HELPER_PATH_REQUIRED'
    }
    $metaBranch = (& $Git -C $MetaRoot branch --show-current 2>$null).Trim()
    $metaHead = (& $Git -C $MetaRoot rev-parse HEAD 2>$null).Trim()
    $metaOrigin = (& $Git -C $MetaRoot rev-parse origin/main 2>$null).Trim()
    $metaSignature = (& $Git -C $MetaRoot -c "gpg.program=$Gpg" log -1 '--format=%G? %GF' 2>$null).Trim()
    $metaDirty = @(& $Git -C $MetaRoot status --porcelain --untracked-files=normal 2>$null)
    $metaTreeBlob = (& $Git -C $MetaRoot rev-parse "HEAD:$MetaRelative" 2>$null).Trim()
    $metaFileBlob = (& $Git -C $MetaRoot hash-object --no-filters -- $PSCommandPath 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $metaBranch -cne 'main' -or $metaHead -notmatch '^[0-9a-f]{40}$' -or
        $metaOrigin -cne $metaHead -or $metaSignature -cne "G $TrustedSigner" -or
        $metaDirty.Count -ne 0 -or $metaTreeBlob -cne $metaFileBlob) {
        Stop-Safe 'SIGNED_CLEAN_META_MAIN_REQUIRED'
    }

    $fullReceipt = Assert-RegularFile $Receipt 524288
    $fullSignature = Assert-RegularFile $Signature 16384
    $fullPython = Assert-RegularFile $PythonPath
    $fullPythonw = Assert-RegularFile (Join-Path (Split-Path $fullPython -Parent) 'pythonw.exe')
    $expectedReceiptPath = Join-Path (Join-Path $RuntimeRoot ("run-$Owner")) 'current-runtime-receipt.json'
    if ([IO.Path]::GetFullPath($fullReceipt) -cne [IO.Path]::GetFullPath($expectedReceiptPath) -or
        [IO.Path]::GetFullPath($fullSignature) -cne ([IO.Path]::GetFullPath($expectedReceiptPath) + '.asc') -or
        (Get-FileHash -LiteralPath $fullReceipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ReceiptSha256) {
        Stop-Safe 'EXACT_CURRENT_RECEIPT_REQUIRED'
    }
    $receiptValue = Read-BoundedJson $fullReceipt 524288
    if ($receiptValue.owner -cne $Owner -or $receiptValue.result -cne 'PASS_NONTRADING_RUNTIME_EPOCH' -or
        $receiptValue.source_profile.deploy_revision -cne $DeployRevision -or
        $receiptValue.trading_started -ne $false -or $receiptValue.orders_submitted -ne 0 -or
        $receiptValue.paid_calls -ne 0 -or $receiptValue.production_trading_qualified -ne $false -or
        $receiptValue.schema_migration_count -ne 19 -or $receiptValue.schema_public_table_count -ne 33) {
        Stop-Safe 'EXACT_ACCEPTED_NONTRADING_RECEIPT_REQUIRED'
    }

    $deployHead = Invoke-GitText @('rev-parse', 'HEAD')
    $deployOrigin = Invoke-GitText @('rev-parse', 'origin/main')
    $deployBranch = Invoke-GitText @('branch', '--show-current')
    $deployDirty = Invoke-GitText @('status', '--porcelain', '--untracked-files=normal')
    $deploySignature = Invoke-GitText @('log', '-1', '--format=%G? %GF')
    if ($deployHead -cne $DeployRevision -or $deployOrigin -cne $DeployRevision -or
        $deployBranch -cne 'main' -or $deployDirty -cne '' -or
        $deploySignature -cne "G $TrustedSigner") {
        Stop-Safe 'EXACT_SIGNED_DEPLOY_MAIN_REQUIRED'
    }

    $oldReportPath = Join-Path (Join-Path $InputsRoot ("host-acceptance-$OldAcceptanceId")) 'acceptance.report.json'
    if ([IO.Path]::GetFullPath($PreviousHostReport) -cne [IO.Path]::GetFullPath($oldReportPath) -or
        $PreviousHostReportSha256 -cne $OldReportSha -or
        (Get-FileHash -LiteralPath (Assert-RegularFile $oldReportPath 524288) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldReportSha) {
        Stop-Safe 'PINNED_PREVIOUS_HOST_FAILURE_EVIDENCE_REQUIRED'
    }
    $oldReportSignature = Assert-RegularFile ($oldReportPath + '.asc') 16384
    $oldFailurePath = Join-Path (Split-Path $oldReportPath -Parent) 'acceptance.failure.json'
    if ((Get-FileHash -LiteralPath (Assert-RegularFile $oldFailurePath 4096) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldFailureSha) {
        Stop-Safe 'ORIGINAL_HOST_FAILURE_MUST_REMAIN_UNCHANGED'
    }
    $oldFailure = Read-BoundedJson $oldFailurePath 4096
    if ($oldFailure.state -cne 'FAILED_CLOSED' -or $oldFailure.owner -cne $Owner -or
        $oldFailure.stage -cne 'ACTUAL_SCHEDULED_ACTION' -or
        $oldFailure.reason -cne 'BOUNDED_HOST_COMMAND_FAILED' -or
        $oldFailure.exception_type -cne 'RuntimeError' -or
        $oldFailure.automatic_retry -ne $false -or $oldFailure.trading_started -ne $false) {
        Stop-Safe 'EXACT_PRESERVED_HOST_FAILURE_REQUIRED'
    }
    $oldReport = Read-BoundedJson $oldReportPath 524288
    if ($oldReport.schema -cne 'kairos.current-runtime-host-acceptance.v1' -or
        $oldReport.state -cne 'PASS_CURRENT_NONTRADING_HOST_ACCEPTANCE' -or
        $oldReport.owner -cne $Owner -or $oldReport.receipt_sha256 -cne $ReceiptSha256 -or
        $oldReport.deploy_revision -cne $DeployRevision -or
        $oldReport.trading_started -ne $false -or $oldReport.orders_submitted -ne 0 -or
        $oldReport.paid_calls -ne 0) {
        Stop-Safe 'PINNED_PREVIOUS_HOST_REPORT_IDENTITY_REQUIRED'
    }
    Assert-TrustedReceiptSignature $oldReportPath $OldReportSha $fullPython

    $newFullReportPath = [IO.Path]::GetFullPath($NewHostReportPath)
    $newHostDirectory = Split-Path $newFullReportPath -Parent
    $newAcceptanceName = Split-Path $newHostDirectory -Leaf
    $newMatch = [regex]::Match($newAcceptanceName, '^host-acceptance-([0-9a-f]{32})$')
    $expectedNewDirectory = Join-Path $InputsRoot $newAcceptanceName
    if (-not $newMatch.Success -or $newMatch.Groups[1].Value -ceq $OldAcceptanceId -or
        [IO.Path]::GetFullPath($newHostDirectory) -cne [IO.Path]::GetFullPath($expectedNewDirectory) -or
        (Split-Path $newFullReportPath -Leaf) -cne 'acceptance.report.json') {
        Stop-Safe 'FRESH_UUID_HOST_REPORT_PATH_REQUIRED'
    }
    $newAcceptanceId = $newMatch.Groups[1].Value
    if ((Test-Path -LiteralPath $newHostDirectory) -or
        (Test-Path -LiteralPath $NewHostReportPath) -or
        (Test-Path -LiteralPath ($NewHostReportPath + '.asc')) -or
        (Test-Path -LiteralPath (Join-Path $newHostDirectory 'acceptance.failure.json'))) {
        Stop-Safe 'FRESH_HOST_ACCEPTANCE_DIRECTORY_MUST_BE_ABSENT'
    }

    $bootPath = Join-Path $DeployRoot 'scripts\runtime_epoch_current_boot.py'
    $cli = @($bootPath, '--receipt', $fullReceipt, '--receipt-sha256', $ReceiptSha256,
        '--signature', $fullSignature)
    $planCode = "import runpy,sys;sys.path.insert(0,r'$DeployRoot/scripts');sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
    $planText = & $fullPython -I -B -c $planCode @cli 2>$null
    if ($LASTEXITCODE -ne 0) { Stop-Safe 'READONLY_NATIVE_OWNER_ADMISSION_FAILED' }
    try { $plan = ($planText -join "`n") | ConvertFrom-Json -ErrorAction Stop }
    catch { Stop-Safe 'READONLY_NATIVE_OWNER_PLAN_REQUIRED' }
    if ($plan.state -cne 'ALREADY_RUNNING' -or $plan.owner -cne $Owner -or $plan.starts -ne 0) {
        Stop-Safe 'HEALTHY_EXACT_OWNER_REQUIRED_BEFORE_TASK_MUTATION'
    }

    $scriptsPath = Join-Path $DeployRoot 'scripts'
    $installerPath = Join-Path $scriptsPath 'Install-CurrentRuntimeBootTask.ps1'
    $installerText = [IO.File]::ReadAllText((Assert-RegularFile $installerPath 262144))
    $templateMatches = [regex]::Matches($installerText, '(?m)^\$bootstrap = "([^"\r\n]+)"\s*$')
    if ($templateMatches.Count -ne 1) { Stop-Safe 'SIGNED_STOCK_BOOTSTRAP_TEMPLATE_CHANGED' }
    $bootstrapTemplate = $templateMatches[0].Groups[1].Value

    $oldTaskName = 'Kairos-CurrentRuntime-' + $Owner.Substring(0, 12) + '-Boot'
    $newTaskName = $oldTaskName + '-ReviewedV2'
    $ownerTaskPrefix = $oldTaskName
    $ownerTasks = @(Get-ScheduledTask | Where-Object { $_.TaskName.StartsWith($ownerTaskPrefix, [StringComparison]::OrdinalIgnoreCase) })
    if ($ownerTasks.Count -ne 1 -or $ownerTasks[0].TaskName -cne $oldTaskName) {
        Stop-Safe 'EXACT_SINGLE_PREDECESSOR_TASK_REQUIRED'
    }
    $oldTask = $ownerTasks[0]
    $oldInfo = Get-ScheduledTaskInfo -TaskName $oldTaskName -ErrorAction Stop
    if ($oldTask.State -cne 'Ready' -or $oldInfo.LastTaskResult -ne 267011 -or
        ($null -ne $oldInfo.LastRunTime -and $oldInfo.LastRunTime.ToString('yyyy-MM-ddTHH:mm:ss') -cne '1999-11-30T00:00:00') -or
        $null -ne $oldInfo.NextRunTime) {
        Stop-Safe 'EXACT_READY_NEVER_RUN_PREDECESSOR_REQUIRED'
    }
    $oldUser = $oldTask.Principal.UserId
    if ((Get-IdentitySid $oldUser) -cne $identity.User.Value -or [string]$oldTask.Principal.RunLevel -cne 'Highest' -or
        [string]$oldTask.Principal.LogonType -cne 'Interactive') {
        Stop-Safe 'EXACT_INTERACTIVE_OWNER_PRINCIPAL_REQUIRED'
    }
    $oldXml = Export-ScheduledTask -TaskName $oldTaskName -ErrorAction Stop
    Assert-LogonTaskXml $oldXml $oldUser
    $oldTaskRecordPath = Join-Path (Split-Path $oldReportPath -Parent) 'task.install.json'
    $oldTaskRecord = Read-BoundedJson $oldTaskRecordPath 4096
    $ownerWork = Join-Path $RuntimeRoot ("run-$Owner")
    $oldBindingPath = Join-Path $ownerWork 'windows-boot-binding.json'
    if ($oldTaskRecord.state -cne 'INSTALLED_NOT_STARTED' -or $oldTaskRecord.owner -cne $Owner -or
        $oldTaskRecord.task_name -cne $oldTaskName -or
        [IO.Path]::GetFullPath($oldTaskRecord.binding) -cne [IO.Path]::GetFullPath($oldBindingPath) -or
        $oldTaskRecord.binding_sha256 -cne $OldBindingSha -or $oldTaskRecord.trading_started -ne $false -or
        (Get-FileHash -LiteralPath $oldBindingPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldBindingSha) {
        Stop-Safe 'EXACT_IMMUTABLE_PREDECESSOR_BINDING_REQUIRED'
    }
    $oldBinding = Read-BoundedJson $oldBindingPath 65536
    if ($oldBinding.schema -cne 'kairos.current-runtime-windows-boot.v1' -or
        $oldBinding.owner -cne $Owner -or $oldBinding.deploy_revision -cne $DeployRevision -or
        $oldBinding.receipt_sha256 -cne $ReceiptSha256 -or
        [IO.Path]::GetFullPath($oldBinding.host_acceptance_report) -cne [IO.Path]::GetFullPath($oldReportPath) -or
        $oldBinding.trading_started -ne $false -or
        [IO.Path]::GetFullPath($oldBinding.scripts) -cne [IO.Path]::GetFullPath($scriptsPath) -or
        [IO.Path]::GetFullPath($oldBinding.pythonw) -cne [IO.Path]::GetFullPath($fullPythonw) -or
        (Get-FileHash -LiteralPath $oldBinding.pythonw -Algorithm SHA256).Hash.ToLowerInvariant() -cne $oldBinding.pythonw_sha256) {
        Stop-Safe 'EXACT_PREDECESSOR_BINDING_CONTENT_REQUIRED'
    }
    $actualScriptHashes = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $scriptsPath -Filter '*.py' -File | Sort-Object Name) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-Safe 'SOURCE_LINKS_REFUSED' }
        $actualScriptHashes[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if ((ConvertTo-Json -InputObject $oldBinding.script_hashes -Compress -Depth 8) -cne
        (ConvertTo-Json -InputObject $actualScriptHashes -Compress -Depth 8)) {
        Stop-Safe 'EXACT_PREDECESSOR_SCRIPT_INVENTORY_REQUIRED'
    }
    $oldBootstrap = Get-Bootstrap $bootstrapTemplate $oldBindingPath $OldBindingSha
    $oldArguments = '-I -B -c "' + $oldBootstrap + '"'
    Assert-TaskProjection $oldTask $oldTaskName $oldBinding.pythonw $oldArguments $DeployRoot $oldUser
    $oldCli = @($bootPath, '--receipt', $fullReceipt, '--receipt-sha256', $ReceiptSha256,
        '--signature', $fullSignature, '--execute')
    if ($oldBinding.argv.Count -ne $oldCli.Count) { Stop-Safe 'EXACT_PREDECESSOR_BOOT_ARGUMENTS_REQUIRED' }
    for ($index = 0; $index -lt $oldCli.Count; $index++) {
        if ([string]$oldBinding.argv[$index] -cne [string]$oldCli[$index]) { Stop-Safe 'EXACT_PREDECESSOR_BOOT_ARGUMENTS_REQUIRED' }
    }

    $newBindingPath = Join-Path $ownerWork 'windows-boot-binding-reviewed-v2.json'
    if ((Get-ScheduledTask -TaskName $newTaskName -ErrorAction SilentlyContinue) -or
        (Test-Path -LiteralPath $newBindingPath) -or
        (((Get-Item -LiteralPath $ownerWork -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Stop-Safe 'REVIEWED_V2_CREATE_ONLY_TARGETS_REQUIRED'
    }

    if (-not $Execute) {
        [ordered]@{
            state='PLAN_ONLY'; owner=$Owner; predecessor_task=$oldTaskName; new_task=$newTaskName
            new_host_report=$NewHostReportPath; previous_failure_retained=$true
            native_plan=$plan.state; task_started=$false; trading_started=$false
        } | ConvertTo-Json -Compress
        return
    }

    if ((Test-Path -LiteralPath $newHostDirectory) -or
        (Test-Path -LiteralPath (Join-Path $ownerWork 'windows-boot-binding-reviewed-v2.json')) -or
        (Get-ScheduledTask -TaskName $newTaskName -ErrorAction SilentlyContinue)) {
        Stop-Safe 'REVIEWED_V2_TARGETS_CHANGED_BEFORE_MUTATION'
    }
    $acceptanceWork = Join-Path $InputsRoot ("reviewed-boot-task-v2-$Owner-$newAcceptanceId")
    New-PrivateDirectory $acceptanceWork
    $oldXmlBytes = [Text.UTF8Encoding]::new($false).GetBytes($oldXml)
    $oldXmlPath = Join-Path $acceptanceWork 'predecessor-v1-task.xml'
    Write-NewBytes $oldXmlPath $oldXmlBytes
    $oldXmlSha256 = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($oldXmlBytes))).Replace('-', '').ToLowerInvariant()

    Disable-ScheduledTask -TaskName $oldTaskName -ErrorAction Stop | Out-Null
    $oldAfterDisable = Get-ScheduledTask -TaskName $oldTaskName -ErrorAction Stop
    if ($oldAfterDisable.State -cne 'Disabled' -or
        (Get-FileHash -LiteralPath $oldBindingPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldBindingSha) {
        Stop-Safe 'PREDECESSOR_TASK_DISABLE_OR_BINDING_PRESERVATION_FAILED'
    }

    $newBinding = [ordered]@{
        schema='kairos.current-runtime-windows-boot.v1'; owner=$Owner; deploy_revision=$DeployRevision
        scripts=$scriptsPath; script_hashes=$actualScriptHashes; pythonw=$oldBinding.pythonw
        pythonw_sha256=$oldBinding.pythonw_sha256; argv=$oldCli
        trading_started=$false; host_acceptance_report=[IO.Path]::GetFullPath($NewHostReportPath)
        receipt_sha256=$ReceiptSha256
    }
    $newBindingBytes = [Text.UTF8Encoding]::new($false).GetBytes(($newBinding | ConvertTo-Json -Depth 8 -Compress))
    Write-NewBytes $newBindingPath $newBindingBytes
    $newBindingSha256 = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($newBindingBytes))).Replace('-', '').ToLowerInvariant()
    $newBootstrap = Get-Bootstrap $bootstrapTemplate $newBindingPath $newBindingSha256
    $newArguments = '-I -B -c "' + $newBootstrap + '"'
    $pythonw = $oldBinding.pythonw
    $newAction = New-ScheduledTaskAction -Execute $pythonw -Argument $newArguments -WorkingDirectory $DeployRoot
    $newTrigger = New-ScheduledTaskTrigger -AtLogOn -User $oldUser
    $newTrigger.Delay = 'PT2M'
    $newPrincipal = New-ScheduledTaskPrincipal -UserId $oldUser -LogonType Interactive -RunLevel Highest
    $newSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 155) -MultipleInstances IgnoreNew -RestartCount 0 -Hidden
    $newSettings.StartWhenAvailable = $false
    Register-ScheduledTask -TaskName $newTaskName -Action $newAction -Trigger $newTrigger -Principal $newPrincipal -Settings $newSettings -Description 'Reviewed V2 exact-owner signed-source non-trading current runtime boot.' | Out-Null

    $newTask = Get-ScheduledTask -TaskName $newTaskName -ErrorAction Stop
    $oldFinal = Get-ScheduledTask -TaskName $oldTaskName -ErrorAction Stop
    $ownerTasksAfter = @(Get-ScheduledTask | Where-Object { $_.TaskName.StartsWith($ownerTaskPrefix, [StringComparison]::OrdinalIgnoreCase) })
    Assert-TaskProjection $newTask $newTaskName $pythonw $newArguments $DeployRoot $oldUser
    if ($newTask.State -cne 'Ready' -or $oldFinal.State -cne 'Disabled' -or
        $ownerTasksAfter.Count -ne 2 -or
        @($ownerTasksAfter | Where-Object { $_.State -ne 'Disabled' }).Count -ne 1 -or
        @($ownerTasksAfter | Where-Object { $_.TaskName -cne $newTaskName -and $_.TaskName -cne $oldTaskName }).Count -ne 0 -or
        (Test-Path -LiteralPath $newHostDirectory) -or
        (Get-FileHash -LiteralPath $oldBindingPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldBindingSha -or
        (Get-FileHash -LiteralPath $oldReportPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldReportSha -or
        (Get-FileHash -LiteralPath $oldFailurePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $OldFailureSha) {
        Stop-Safe 'REVIEWED_V2_READBACK_REQUIRED'
    }
    [ordered]@{
        state='INSTALLED_NOT_STARTED'; owner=$Owner; predecessor_task=$oldTaskName; new_task_name=$newTaskName
        old_task_xml_sha256=$oldXmlSha256; new_binding_path=$newBindingPath
        new_binding_sha256=$newBindingSha256; host_acceptance_report=[IO.Path]::GetFullPath($NewHostReportPath)
        task_started=$false; trading_started=$false; paid_calls=0
    } | ConvertTo-Json -Compress
}
catch {
    $safeReason = [string]$_.Exception.Message
    if ($safeReason -cnotmatch '^[A-Z0-9_]{1,160}$') { $safeReason = 'DETAILS_NOT_DISCLOSED' }
    [ordered]@{ state='FAILED_CLOSED'; reason=$safeReason; error_type=$_.Exception.GetType().Name; source_line=$_.InvocationInfo.ScriptLineNumber; trading_started=$false } | ConvertTo-Json -Compress
    exit 2
}
