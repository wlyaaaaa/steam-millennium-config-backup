$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$snapshotScript = Join-Path $repoRoot 'tools\snapshot-millennium-config.ps1'

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
