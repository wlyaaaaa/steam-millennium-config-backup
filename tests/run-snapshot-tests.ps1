$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$snapshotScript = Join-Path $repoRoot 'tools\snapshot-millennium-config.ps1'
$registrationScript = Join-Path $repoRoot 'tools\register-millennium-config-snapshot-task.ps1'

$script:Failures = 0

function Assert-True {
    param(
        [Parameter(Mandatory = $true)] [bool] $Condition,
        [Parameter(Mandatory = $true)] [string] $Name
    )

    if (-not $Condition) {
        Write-Host "FAIL: $Name"
        $script:Failures++
        return
    }

    Write-Host "PASS: $Name"
}

function Assert-False {
    param(
        [Parameter(Mandatory = $true)] [bool] $Condition,
        [Parameter(Mandatory = $true)] [string] $Name
    )

    Assert-True (-not $Condition) $Name
}

$registrationSource = Get-Content -LiteralPath $registrationScript -Raw
Assert-True ($registrationSource -match '(?m)^\s*-RestartCount\s+3\s+`?\s*$') 'scheduled snapshot retries transient failures three times'
Assert-True ($registrationSource -match '(?m)^\s*-RestartInterval\s+\(New-TimeSpan\s+-Minutes\s+15\)\s+`?\s*$') 'scheduled snapshot spaces retries by fifteen minutes'

$caseRoot = Join-Path $env:TEMP ("millennium-snapshot-test-" + [guid]::NewGuid().ToString('N'))
$sourceRoot = Join-Path $caseRoot 'source'
$destRoot = Join-Path $caseRoot 'dest'
$runtimeRoot = Join-Path $caseRoot 'runtime'

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot 'config') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot 'plugins\sample-plugin') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot 'themes\sample-theme') | Out-Null
    New-Item -ItemType Directory -Force -Path $destRoot | Out-Null

    Set-Content -LiteralPath (Join-Path $sourceRoot 'config\config.json') -Value '{"network":{"proxyPassword":"","proxyUsername":""}}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'config\quick.css') -Value 'body { color: lime; }' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'config\id_cache.json') -Value '{"steamid":"STEAMID64_REDACTED_TEST_VALUE"}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'plugins\sample-plugin\plugin.json') -Value '{"name":"sample"}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'plugins\sample-plugin\cache.json') -Value '{"library":["private"]}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'plugins\sample-plugin\plugin.js') -Value 'console.log("nope")' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'themes\sample-theme\metadata.json') -Value '{"name":"theme"}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'themes\sample-theme\preview.png') -Value 'not an image' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $sourceRoot 'debug.log') -Value 'runtime log' -Encoding UTF8

    & $snapshotScript -SourceRoot $sourceRoot -DestinationRoot $destRoot -RuntimeRoot $runtimeRoot -Force | Out-Host

    Assert-True (Test-Path -LiteralPath (Join-Path $destRoot 'config\config.json')) 'copies config.json'
    Assert-True (Test-Path -LiteralPath (Join-Path $destRoot 'config\quick.css')) 'copies quick.css'
    Assert-True (Test-Path -LiteralPath (Join-Path $destRoot 'plugins\sample-plugin\plugin.json')) 'copies plugin manifest'
    Assert-True (Test-Path -LiteralPath (Join-Path $destRoot 'themes\sample-theme\metadata.json')) 'copies theme metadata'
    Assert-False (Test-Path -LiteralPath (Join-Path $destRoot 'config\id_cache.json')) 'excludes SteamID cache'
    Assert-False (Test-Path -LiteralPath (Join-Path $destRoot 'plugins\sample-plugin\cache.json')) 'excludes game/library cache'
    Assert-False (Test-Path -LiteralPath (Join-Path $destRoot 'plugins\sample-plugin\plugin.js')) 'excludes plugin source'
    Assert-False (Test-Path -LiteralPath (Join-Path $destRoot 'themes\sample-theme\preview.png')) 'excludes theme assets'
    Assert-False (Test-Path -LiteralPath (Join-Path $destRoot 'debug.log')) 'excludes runtime logs'

    $guardSourceRoot = Join-Path $caseRoot 'guard-source'
    $guardDestRoot = Join-Path $caseRoot 'guard-dest'
    $guardRuntimeRoot = Join-Path $caseRoot 'guard-runtime'
    New-Item -ItemType Directory -Force -Path (Join-Path $guardSourceRoot 'config') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $guardDestRoot 'config') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $guardDestRoot 'tools') | Out-Null
    Set-Content -LiteralPath (Join-Path $guardSourceRoot 'config\config.json') -Value '{"value":"current"}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $guardDestRoot 'config\config.json') -Value '{"value":"baseline"}' -Encoding UTF8
    Copy-Item -LiteralPath $snapshotScript -Destination (Join-Path $guardDestRoot 'tools\snapshot-millennium-config.ps1')
    git -C $guardDestRoot init --quiet
    git -C $guardDestRoot config user.name 'Snapshot Test'
    git -C $guardDestRoot config user.email 'snapshot-test@example.invalid'
    git -C $guardDestRoot add -- .
    git -C $guardDestRoot commit --quiet -m 'fixture'

    Set-Content -LiteralPath (Join-Path $guardDestRoot 'config\config.json') -Value '{"value":"current"}' -Encoding UTF8
    Add-Content -LiteralPath (Join-Path $guardDestRoot 'tools\snapshot-millennium-config.ps1') -Value '# source-only test edit'
    $sourceMatchingAllowed = $true
    try {
        & $snapshotScript -SourceRoot $guardSourceRoot -DestinationRoot $guardDestRoot -RuntimeRoot $guardRuntimeRoot -Force | Out-Host
    }
    catch {
        $sourceMatchingAllowed = $false
    }
    Assert-True $sourceMatchingAllowed 'allows source-matching snapshot files and a source-only runner edit'

    Set-Content -LiteralPath (Join-Path $guardDestRoot 'config\config.json') -Value '{"value":"manual-divergence"}' -Encoding UTF8
    $divergentBlocked = $false
    try {
        & $snapshotScript -SourceRoot $guardSourceRoot -DestinationRoot $guardDestRoot -RuntimeRoot $guardRuntimeRoot -Force | Out-Host
    }
    catch {
        $divergentBlocked = $_.Exception.Message -like 'Destination git workspace is dirty*'
    }
    Assert-True $divergentBlocked 'blocks divergent manual snapshot edits'

    Set-Content -LiteralPath (Join-Path $guardDestRoot 'config\config.json') -Value '{"value":"current"}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $guardDestRoot 'notes.txt') -Value 'unrelated change' -Encoding UTF8
    $unrelatedBlocked = $false
    try {
        & $snapshotScript -SourceRoot $guardSourceRoot -DestinationRoot $guardDestRoot -RuntimeRoot $guardRuntimeRoot -Force | Out-Host
    }
    catch {
        $unrelatedBlocked = $_.Exception.Message -like 'Destination git workspace is dirty*'
    }
    Assert-True $unrelatedBlocked 'blocks unrelated dirty destination files'

    $fakeRepoRoot = Join-Path $caseRoot 'fake-repo'
    $fakeToolsRoot = Join-Path $fakeRepoRoot 'tools'
    $fakeRuntimeRoot = Join-Path $caseRoot 'winps-runtime'
    New-Item -ItemType Directory -Force -Path $fakeToolsRoot | Out-Null
    $fakeSnapshotScript = Join-Path $fakeToolsRoot 'snapshot-millennium-config.ps1'
    Copy-Item -LiteralPath $snapshotScript -Destination $fakeSnapshotScript -Force

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fakeSnapshotScript -SourceRoot $sourceRoot -RuntimeRoot $fakeRuntimeRoot -ThrottleDays 0 -Force -AllowDirtyDestination | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Windows PowerShell compatibility check failed with exit code $LASTEXITCODE"
    }

    Assert-True (Test-Path -LiteralPath (Join-Path $fakeRepoRoot 'config\config.json')) 'runs under Windows PowerShell with default destination root'
}
finally {
    if (Test-Path -LiteralPath $caseRoot) {
        Remove-Item -LiteralPath $caseRoot -Recurse -Force
    }
}

if ($script:Failures -gt 0) {
    throw "$script:Failures test(s) failed"
}

Write-Host 'All snapshot tests passed.'
