Set-StrictMode -Version Latest

function Get-ReleaseRequiredProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if ($null -eq $Object -or $null -eq $Object.PSObject.Properties[$Name]) {
        throw "$Context is missing required property '$Name'"
    }
    return $Object.PSObject.Properties[$Name].Value
}

function Read-ReleaseProjectionJson {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Release source projection file is missing: $Path"
    }
    $value = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($null -eq $value -or $value -is [System.Array] -or $value -is [string]) {
        throw "Release source projection file must contain a JSON object: $Path"
    }
    return $value
}

function Assert-ReleaseProjectionNameSet {
    param(
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string[]]$Actual,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $expectedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $actualSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($name in $Expected) { $null = $expectedSet.Add($name) }
    foreach ($name in $Actual) { $null = $actualSet.Add($name) }
    if ($expectedSet.Count -ne $Expected.Count -or $actualSet.Count -ne $Actual.Count -or
        (Compare-Object -ReferenceObject ($Expected | Sort-Object -CaseSensitive) `
            -DifferenceObject ($Actual | Sort-Object -CaseSensitive) -CaseSensitive)) {
        throw "$Context name set differs from the current-release projection"
    }
}

function Assert-ReleaseProjectionSchemaVersion {
    param(
        [Parameter(Mandatory = $true)]$Lock,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $version = Get-ReleaseRequiredProperty -Object $Lock -Name "schema_version" -Context $Context
    if (($version -isnot [int] -and $version -isnot [long]) -or $version -ne 1) {
        throw "$Context schema_version must be the integer 1"
    }
}

function Get-ReleaseProjectionEntry {
    param(
        [Parameter(Mandatory = $true)][object[]]$Entries,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $matches = @($Entries | Where-Object { $_.name -ceq $Name })
    if ($matches.Count -ne 1) {
        throw "Current-release manifest must contain exactly one source entry for $Name"
    }
    $entry = $matches[0]
    if ($entry.revision -isnot [string] -or [string]::IsNullOrWhiteSpace($entry.revision) -or
        $entry.origin -isnot [string] -or [string]::IsNullOrWhiteSpace($entry.origin)) {
        throw "Current-release manifest source identity is incomplete for $Name"
    }
    return $entry
}

function Assert-ReleaseProjectionReadiness {
    param(
        [Parameter(Mandatory = $true)]$Lock,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $readiness = Get-ReleaseRequiredProperty -Object $Lock -Name "readiness" -Context $Context
    if ($null -eq $readiness -or $readiness -is [System.Array] -or $readiness -is [string]) {
        throw "$Context readiness must be a JSON object"
    }
    foreach ($name in @("paper_qualified", "alpha_ready", "live_ready")) {
        $value = Get-ReleaseRequiredProperty -Object $readiness -Name $name -Context "$Context readiness"
        if ($value -isnot [bool] -or $value -ne $false) {
            throw "$Context readiness.$name must be the boolean false"
        }
    }
    $policy = Get-ReleaseRequiredProperty -Object $readiness -Name "strategy_policy" -Context "$Context readiness"
    if ($policy -isnot [string] -or $policy -cne "REJECT_ALL") {
        throw "$Context readiness.strategy_policy must remain REJECT_ALL"
    }
}

function Assert-ReleaseProjectionDependencies {
    param(
        [Parameter(Mandatory = $true)]$Lock,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNames,
        [Parameter(Mandatory = $true)][object[]]$ManifestEntries,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $dependencies = Get-ReleaseRequiredProperty -Object $Lock -Name "dependencies" -Context $Context
    if ($null -eq $dependencies -or $dependencies -is [System.Array] -or $dependencies -is [string]) {
        throw "$Context dependencies must be a JSON object"
    }
    $dependencyNames = @($dependencies.PSObject.Properties | ForEach-Object { $_.Name })
    Assert-ReleaseProjectionNameSet -Expected $ExpectedNames -Actual $dependencyNames -Context "$Context dependencies"
    foreach ($name in $ExpectedNames) {
        $dependency = Get-ReleaseRequiredProperty -Object $dependencies -Name $name -Context "$Context dependencies"
        if ($null -eq $dependency -or $dependency -is [System.Array] -or $dependency -is [string]) {
            throw "$Context dependency $name must be a JSON object"
        }
        $repository = Get-ReleaseRequiredProperty -Object $dependency -Name "repository" -Context "$Context dependency $name"
        $revision = Get-ReleaseRequiredProperty -Object $dependency -Name "revision" -Context "$Context dependency $name"
        if ($repository -isnot [string] -or $revision -isnot [string]) {
            throw "$Context dependency $name repository and revision must be strings"
        }
        $expected = Get-ReleaseProjectionEntry -Entries $ManifestEntries -Name $name
        $expectedRepository = $expected.origin
        if ($expectedRepository.EndsWith(".git", [System.StringComparison]::Ordinal)) {
            $expectedRepository = $expectedRepository.Substring(0, $expectedRepository.Length - 4)
        }
        if ($repository -cne $expectedRepository -or $revision -cne $expected.revision) {
            throw "$Context dependency does not match the current-release manifest: $name"
        }
    }
}

function Assert-ReleaseSourceProjection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$DeployRoot
    )

    $manifestEntries = @($Manifest.repositories)
    $runtimeGateNames = @(
        "kairos-core", "kairos-persistence", "kairos-strategy-engine", "kairos-router",
        "kairos-llm", "kairos-aggregator", "kairos-risk-manager", "kairos-execution-engine"
    )
    $compositionNames = @(
        "kairos-core", "kairos-persistence", "kairos-llm", "kairos-text-scouts",
        "kairos-macro-strategist", "kairos-router", "kairos-aggregator",
        "kairos-risk-manager", "kairos-strategy-engine"
    )
    $gateSpecifications = @(
        [pscustomobject]@{
            FileName = "current-release-gate.sources.lock.json"
            Purpose = "current-release-reject-all-integration-gate"
            Classification = "ENGINEERING_ONLY"
            Dependencies = $runtimeGateNames
        },
        [pscustomobject]@{
            FileName = "sim-full-path.sources.lock.json"
            Purpose = "isolated-full-path-market-data-simulator"
            Classification = "SIMULATED"
            Dependencies = $runtimeGateNames
        },
        [pscustomobject]@{
            FileName = "tests\text_macro_router_gate\source-lock.json"
            Purpose = "real-producer-router-review-macro-risk-composed-contracts"
            Classification = "OFFLINE_ENGINEERING_FIXTURE"
            Dependencies = $compositionNames
        }
    )

    foreach ($gate in $gateSpecifications) {
        $context = $gate.FileName
        $lock = Read-ReleaseProjectionJson -Path (Join-Path $DeployRoot $gate.FileName)
        Assert-ReleaseProjectionSchemaVersion -Lock $lock -Context $context
        $purpose = Get-ReleaseRequiredProperty -Object $lock -Name "purpose" -Context $context
        $classification = Get-ReleaseRequiredProperty -Object $lock -Name "classification" -Context $context
        if ($purpose -isnot [string] -or $purpose -cne $gate.Purpose -or
            $classification -isnot [string] -or $classification -cne $gate.Classification) {
            throw "Current-release source lock has an unexpected identity: $context"
        }
        Assert-ReleaseProjectionReadiness -Lock $lock -Context $context
        Assert-ReleaseProjectionDependencies -Lock $lock -ExpectedNames $gate.Dependencies `
            -ManifestEntries $manifestEntries -Context $context
    }

    $runtimeLock = Read-ReleaseProjectionJson -Path (Join-Path $DeployRoot "sources.lock.json")
    Assert-ReleaseProjectionSchemaVersion -Lock $runtimeLock -Context "sources.lock.json"
    $runtimeDependencyNames = @("kairos-core", "kairos-llm", "kairos-persistence")
    $runtimeDependencies = Get-ReleaseRequiredProperty -Object $runtimeLock -Name "dependencies" -Context "sources.lock.json"
    if ($null -eq $runtimeDependencies -or $runtimeDependencies -is [System.Array] -or $runtimeDependencies -is [string]) {
        throw "sources.lock.json dependencies must be a JSON object"
    }
    $runtimeDependencyKeys = @($runtimeDependencies.PSObject.Properties | ForEach-Object { $_.Name })
    Assert-ReleaseProjectionNameSet -Expected $runtimeDependencyNames -Actual $runtimeDependencyKeys -Context "sources.lock.json dependencies"
    foreach ($name in $runtimeDependencyNames) {
        $revision = Get-ReleaseRequiredProperty -Object $runtimeDependencies -Name $name -Context "sources.lock.json dependencies"
        if ($revision -isnot [string]) { throw "sources.lock.json dependency revision must be a string: $name" }
        $expected = Get-ReleaseProjectionEntry -Entries $manifestEntries -Name $name
        if ($revision -cne $expected.revision) {
            throw "Runtime dependency does not match the current-release manifest: $name"
        }
    }

    $runtimeServiceMap = [ordered]@{
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
    $runtimeServices = Get-ReleaseRequiredProperty -Object $runtimeLock -Name "services" -Context "sources.lock.json"
    if ($null -eq $runtimeServices -or $runtimeServices -is [System.Array] -or $runtimeServices -is [string]) {
        throw "sources.lock.json services must be a JSON object"
    }
    $serviceNames = @($runtimeServices.PSObject.Properties | ForEach-Object { $_.Name })
    Assert-ReleaseProjectionNameSet -Expected @($runtimeServiceMap.Keys) -Actual $serviceNames -Context "sources.lock.json services"
    foreach ($serviceName in $runtimeServiceMap.Keys) {
        $componentName = $runtimeServiceMap[$serviceName]
        $service = Get-ReleaseRequiredProperty -Object $runtimeServices -Name $serviceName -Context "sources.lock.json services"
        if ($null -eq $service -or $service -is [System.Array] -or $service -is [string]) {
            throw "Runtime service must be a JSON object: $serviceName"
        }
        $repository = Get-ReleaseRequiredProperty -Object $service -Name "repository" -Context "Runtime service $serviceName"
        $revision = Get-ReleaseRequiredProperty -Object $service -Name "revision" -Context "Runtime service $serviceName"
        if ($repository -isnot [string] -or $revision -isnot [string]) {
            throw "Runtime service $serviceName repository and revision must be strings"
        }
        $expected = Get-ReleaseProjectionEntry -Entries $manifestEntries -Name $componentName
        $expectedRepository = $expected.origin
        if ($expectedRepository.EndsWith(".git", [System.StringComparison]::Ordinal)) {
            $expectedRepository = $expectedRepository.Substring(0, $expectedRepository.Length - 4)
        }
        if ($repository -cne $expectedRepository -or $revision -cne $expected.revision) {
            throw "Runtime service does not match the current-release manifest: $serviceName"
        }
    }
}
