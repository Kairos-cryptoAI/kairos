[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $repoRoot "scripts\ReleaseSourceProjection.ps1")

$temporaryBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$temporaryName = "kairos-release-projection-test-" + [guid]::NewGuid().ToString("N")
$temporaryRoot = [System.IO.Path]::GetFullPath((Join-Path $temporaryBase $temporaryName))
$deployRoot = Join-Path $temporaryRoot "deploy"
$gatePaths = @(
    "current-release-gate.sources.lock.json",
    "sim-full-path.sources.lock.json",
    "tests\text_macro_router_gate\source-lock.json"
)

function Copy-JsonValue {
    param([Parameter(Mandatory = $true)]$Value)
    return (ConvertFrom-Json -InputObject (ConvertTo-Json -InputObject $Value -Depth 100))
}

function Write-JsonValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $parent -Force
    }
    $json = ConvertTo-Json -InputObject $Value -Depth 100
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Get-ManifestSource {
    param([Parameter(Mandatory = $true)][string]$Name)
    $matches = @($manifest.repositories | Where-Object { $_.name -ceq $Name })
    if ($matches.Count -ne 1) { throw "Manifest fixture must identify exactly one source: $Name" }
    $origin = $matches[0].origin
    if ($origin.EndsWith(".git", [System.StringComparison]::Ordinal)) {
        $origin = $origin.Substring(0, $origin.Length - 4)
    }
    return [pscustomobject]@{ repository = $origin; revision = $matches[0].revision }
}

function New-GateLock {
    param(
        [Parameter(Mandatory = $true)][string]$Purpose,
        [Parameter(Mandatory = $true)][string]$Classification,
        [Parameter(Mandatory = $true)][string[]]$DependencyNames
    )
    $dependencies = [ordered]@{}
    foreach ($name in $DependencyNames) { $dependencies[$name] = Get-ManifestSource -Name $name }
    return [pscustomobject]@{
        schema_version = 1
        purpose = $Purpose
        classification = $Classification
        readiness = [pscustomobject]@{
            paper_qualified = $false
            alpha_ready = $false
            live_ready = $false
            strategy_policy = "REJECT_ALL"
        }
        dependencies = [pscustomobject]$dependencies
    }
}

function New-RuntimeLock {
    $dependencies = [ordered]@{}
    foreach ($name in @("kairos-core", "kairos-llm", "kairos-persistence")) {
        $dependencies[$name] = (Get-ManifestSource -Name $name).revision
    }
    $serviceMap = [ordered]@{
        "quant-scouts" = "kairos-quant-scouts"
        "strategy-engine" = "kairos-strategy-engine"
        "text-scouts" = "kairos-text-scouts"
        "router" = "kairos-router"
        "aggregator" = "kairos-aggregator"
        "macro-strategist" = "kairos-macro-strategist"
        "risk-manager" = "kairos-risk-manager"
        "execution-engine" = "kairos-execution-engine"
        "ops-exporter" = "kairos-persistence"
    }
    $services = [ordered]@{}
    foreach ($serviceName in $serviceMap.Keys) {
        $source = Get-ManifestSource -Name $serviceMap[$serviceName]
        $services[$serviceName] = [pscustomobject]@{
            repository = $source.repository
            revision = $source.revision
            package_dir = "fixture_package"
            command = "fixture-command"
        }
    }
    return [pscustomobject]@{
        schema_version = 1
        dependencies = [pscustomobject]$dependencies
        services = [pscustomobject]$services
    }
}

function New-Fixture {
    param(
        [Parameter(Mandatory = $true)]$Locks,
        [Parameter(Mandatory = $true)]$RuntimeLock
    )
    foreach ($fileName in $gatePaths) {
        Write-JsonValue -Path (Join-Path $deployRoot $fileName) -Value $Locks[$fileName]
    }
    Write-JsonValue -Path (Join-Path $deployRoot "sources.lock.json") -Value $RuntimeLock
}

function Assert-ProjectionFails {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)]$Locks,
        [Parameter(Mandatory = $true)]$RuntimeLock,
        [string]$ExpectedText = ""
    )
    New-Fixture -Locks $Locks -RuntimeLock $RuntimeLock
    try {
        Assert-ReleaseSourceProjection -Manifest $manifest -DeployRoot $deployRoot
    }
    catch {
        if (-not [string]::IsNullOrWhiteSpace($ExpectedText) -and
            -not $_.Exception.Message.Contains($ExpectedText)) {
            throw "$Label failed for an unexpected reason: $($_.Exception.Message)"
        }
        return
    }
    throw "$Label unexpectedly passed source projection validation"
}

try {
    $null = New-Item -ItemType Directory -Path $deployRoot -Force
    $manifest = Get-Content -LiteralPath (Join-Path $repoRoot "config\current-release.json") -Raw | ConvertFrom-Json
    $runtimeGateNames = @(
        "kairos-core", "kairos-persistence", "kairos-strategy-engine", "kairos-router",
        "kairos-llm", "kairos-aggregator", "kairos-risk-manager", "kairos-execution-engine"
    )
    $compositionNames = @(
        "kairos-core", "kairos-persistence", "kairos-llm", "kairos-text-scouts",
        "kairos-macro-strategist", "kairos-router", "kairos-aggregator",
        "kairos-risk-manager", "kairos-strategy-engine"
    )
    $baselineLocks = @{}
    $baselineLocks[$gatePaths[0]] = New-GateLock -Purpose "current-release-reject-all-integration-gate" `
        -Classification "ENGINEERING_ONLY" -DependencyNames $runtimeGateNames
    $baselineLocks[$gatePaths[1]] = New-GateLock -Purpose "isolated-full-path-market-data-simulator" `
        -Classification "SIMULATED" -DependencyNames $runtimeGateNames
    $baselineLocks[$gatePaths[2]] = New-GateLock -Purpose "real-producer-router-review-macro-risk-composed-contracts" `
        -Classification "OFFLINE_ENGINEERING_FIXTURE" -DependencyNames $compositionNames
    $baselineRuntime = New-RuntimeLock

    New-Fixture -Locks $baselineLocks -RuntimeLock $baselineRuntime
    Assert-ReleaseSourceProjection -Manifest $manifest -DeployRoot $deployRoot

    foreach ($fileName in @("current-release-gate.sources.lock.json", "sim-full-path.sources.lock.json")) {
        $locks = @{}
        foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
        $locks[$fileName].dependencies.PSObject.Properties.Remove("kairos-core")
        Assert-ProjectionFails -Label "$fileName lost original gate dependency" -Locks $locks `
            -RuntimeLock $baselineRuntime -ExpectedText "name set differs"

        $locks = @{}
        foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
        Add-Member -InputObject $locks[$fileName].dependencies -MemberType NoteProperty -Name "kairos-quant-scouts" `
            -Value ([pscustomobject]@{ repository = "https://github.com/Kairos-cryptoAI/kairos-quant-scouts"; revision = "0000000000000000000000000000000000000000" })
        Assert-ProjectionFails -Label "$fileName gained an unexpected gate dependency" -Locks $locks `
            -RuntimeLock $baselineRuntime -ExpectedText "name set differs"
    }

    $compositionPath = "tests\text_macro_router_gate\source-lock.json"
    $composition = Copy-JsonValue $baselineLocks[$compositionPath]
    $composition.dependencies.PSObject.Properties.Remove("kairos-text-scouts")
    Assert-ProjectionFails -Label "missing composition dependency" -Locks @{
        "current-release-gate.sources.lock.json" = $baselineLocks["current-release-gate.sources.lock.json"]
        "sim-full-path.sources.lock.json" = $baselineLocks["sim-full-path.sources.lock.json"]
        $compositionPath = $composition
    } -RuntimeLock $baselineRuntime -ExpectedText "name set differs"

    $composition = Copy-JsonValue $baselineLocks[$compositionPath]
    Add-Member -InputObject $composition.dependencies -MemberType NoteProperty -Name "kairos-quant-scouts" -Value ([pscustomobject]@{ repository = "https://github.com/Kairos-cryptoAI/kairos-quant-scouts"; revision = "0000000000000000000000000000000000000000" })
    Assert-ProjectionFails -Label "extra composition dependency" -Locks @{
        "current-release-gate.sources.lock.json" = $baselineLocks["current-release-gate.sources.lock.json"]
        "sim-full-path.sources.lock.json" = $baselineLocks["sim-full-path.sources.lock.json"]
        $compositionPath = $composition
    } -RuntimeLock $baselineRuntime -ExpectedText "name set differs"

    foreach ($name in @("kairos-text-scouts", "kairos-macro-strategist")) {
        foreach ($field in @("revision", "repository")) {
            $composition = Copy-JsonValue $baselineLocks[$compositionPath]
            $composition.dependencies.PSObject.Properties[$name].Value.$field = "mutated"
            Assert-ProjectionFails -Label "composition $name $field drift" -Locks @{
                "current-release-gate.sources.lock.json" = $baselineLocks["current-release-gate.sources.lock.json"]
                "sim-full-path.sources.lock.json" = $baselineLocks["sim-full-path.sources.lock.json"]
                $compositionPath = $composition
            } -RuntimeLock $baselineRuntime
        }
    }

    foreach ($serviceName in @(
        "quant-scouts", "strategy-engine", "text-scouts", "router", "aggregator",
        "macro-strategist", "risk-manager", "execution-engine", "ops-exporter"
    )) {
        foreach ($field in @("revision", "repository")) {
            $runtime = Copy-JsonValue $baselineRuntime
            $runtime.services.PSObject.Properties[$serviceName].Value.$field = "mutated"
            Assert-ProjectionFails -Label "runtime $serviceName $field drift" -Locks $baselineLocks -RuntimeLock $runtime
        }
    }
    foreach ($dependencyName in @("kairos-core", "kairos-llm", "kairos-persistence")) {
        $runtime = Copy-JsonValue $baselineRuntime
        $runtime.dependencies.PSObject.Properties[$dependencyName].Value = "mutated"
        Assert-ProjectionFails -Label "runtime dependency $dependencyName drift" -Locks $baselineLocks -RuntimeLock $runtime
    }

    foreach ($fileName in $gatePaths) {
        foreach ($field in @("paper_qualified", "alpha_ready", "live_ready")) {
            foreach ($mode in @("missing", "string", "true")) {
                $locks = @{}
                foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
                $readiness = $locks[$fileName].readiness
                if ($mode -eq "missing") {
                    $readiness.PSObject.Properties.Remove($field)
                }
                elseif ($mode -eq "string") {
                    $readiness.PSObject.Properties[$field].Value = "false"
                }
                else {
                    $readiness.PSObject.Properties[$field].Value = $true
                }
                Assert-ProjectionFails -Label "$fileName readiness $field $mode" -Locks $locks -RuntimeLock $baselineRuntime
            }
        }
        $locks = @{}
        foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
        $locks[$fileName].readiness.strategy_policy = "ALLOW"
        Assert-ProjectionFails -Label "$fileName readiness policy" -Locks $locks -RuntimeLock $baselineRuntime
    }

    foreach ($fileName in $gatePaths) {
        foreach ($mode in @("missing", "boolean", "string", "wrong")) {
            $locks = @{}
            foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
            if ($mode -eq "missing") {
                $locks[$fileName].PSObject.Properties.Remove("schema_version")
            }
            elseif ($mode -eq "boolean") {
                $locks[$fileName].schema_version = $true
            }
            elseif ($mode -eq "string") {
                $locks[$fileName].schema_version = "1"
            }
            else {
                $locks[$fileName].schema_version = 2
            }
            Assert-ProjectionFails -Label "$fileName schema version $mode" -Locks $locks `
                -RuntimeLock $baselineRuntime
        }
    }

    foreach ($mode in @("missing", "boolean", "string", "wrong")) {
        $runtime = Copy-JsonValue $baselineRuntime
        if ($mode -eq "missing") {
            $runtime.PSObject.Properties.Remove("schema_version")
        }
        elseif ($mode -eq "boolean") {
            $runtime.schema_version = $true
        }
        elseif ($mode -eq "string") {
            $runtime.schema_version = "1"
        }
        else {
            $runtime.schema_version = 2
        }
        Assert-ProjectionFails -Label "sources.lock.json schema version $mode" -Locks $baselineLocks `
            -RuntimeLock $runtime
    }

    $locks = @{}
    foreach ($candidate in $gatePaths) { $locks[$candidate] = Copy-JsonValue $baselineLocks[$candidate] }
    $locks["current-release-gate.sources.lock.json"].dependencies.PSObject.Properties.Remove("kairos-core")
    Add-Member -InputObject $locks["current-release-gate.sources.lock.json"].dependencies `
        -MemberType NoteProperty -Name "Kairos-core" -Value (Get-ManifestSource -Name "kairos-core")
    Assert-ProjectionFails -Label "dependency comparison is case-sensitive" -Locks $locks `
        -RuntimeLock $baselineRuntime -ExpectedText "name set differs"

    Write-Host "Current-release source projection regression tests passed."
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot -PathType Container) {
        $resolvedTemporaryRoot = (Resolve-Path -LiteralPath $temporaryRoot).ProviderPath
        if ($resolvedTemporaryRoot -cne $temporaryRoot -or
            -not $resolvedTemporaryRoot.StartsWith($temporaryBase, [System.StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedTemporaryRoot) -cnotmatch '^kairos-release-projection-test-[0-9a-f]{32}$') {
            throw "Refusing cleanup outside the exact disposable projection fixture"
        }
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
