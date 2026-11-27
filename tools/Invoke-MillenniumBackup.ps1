#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Snapshot','Status','Live','Verify','Replicate','RestorePlan','Restore','Rollback','Recover')]
    [string]$Mode = 'Status',
    [string]$SourceRoot = '',
    [string]$DestinationRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RuntimeRoot = '',
    [string]$TargetRoot = '',
    [string]$MachineConfig = '',
    [string]$PythonExecutable = '',
    [string]$ExpectedPlan = '',
    [string]$RollbackId = '',
    [ValidateRange(2,32)][int]$Keep = 4,
    [switch]$AdoptExisting,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$engine = Join-Path $PSScriptRoot 'millennium_backup.py'
$destination = [IO.Path]::GetFullPath($DestinationRoot)
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $destination 'runtime' }
$config = $null
# Only the actual registered checkout on this host inherits the machine mapping.
$defaultMachine = 'E:\PCConfig\registries\steam_millennium_backup.json'
if (-not $MachineConfig -and $Mode -in @('Snapshot','Status','Live') -and (Test-Path -LiteralPath $defaultMachine -PathType Leaf)) {
    $candidate = Get-Content -LiteralPath $defaultMachine -Raw | ConvertFrom-Json
    if ([string]::Equals($destination, [IO.Path]::GetFullPath($candidate.project_root), [StringComparison]::OrdinalIgnoreCase) -and $candidate.machine_name -eq $env:COMPUTERNAME) { $MachineConfig = $defaultMachine }
}
if ($MachineConfig) {
    $config = Get-Content -LiteralPath $MachineConfig -Raw | ConvertFrom-Json
    if ($config.schema -ne 'pcconfig.steam-millennium-backup.v1' -or
        -not [string]::Equals($destination, [IO.Path]::GetFullPath($config.project_root), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'machine_config_project_binding_mismatch'
    }
    if ($config.machine_name -ne $env:COMPUTERNAME) { throw 'machine_config_host_mismatch' }
    if ($SourceRoot -and -not [string]::Equals([IO.Path]::GetFullPath($SourceRoot), [IO.Path]::GetFullPath($config.source_root), [StringComparison]::OrdinalIgnoreCase)) { throw 'machine_config_source_override_mismatch' }
    if (-not $SourceRoot) { $SourceRoot = [string]$config.source_root }
    if (-not $PythonExecutable) { $PythonExecutable = [string]$config.python_executable }
}
if (-not $PythonExecutable) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python 3.11+ is required. Set -PythonExecutable to an installed interpreter.' }
    $PythonExecutable = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'python_executable_missing' }
$probe = & $PythonExecutable -I -B -c 'import sys; print("supported" if (3,11) <= sys.version_info[:2] < (4,0) else "unsupported")'
if ($LASTEXITCODE -ne 0 -or [string]$probe -ne 'supported') { throw 'python_3_11_or_newer_required' }
if (-not $SourceRoot -and $Mode -in @('Snapshot','Status','Live')) {
    $candidates = [Collections.Generic.List[string]]::new()
    $steam = Get-ItemProperty -LiteralPath 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction SilentlyContinue
    if ($steam -and $steam.SteamPath) { $candidates.Add((Join-Path $steam.SteamPath 'millennium')) }
    if (${env:ProgramFiles(x86)}) { $candidates.Add((Join-Path ${env:ProgramFiles(x86)} 'Steam\millennium')) }
    if ($env:ProgramFiles) { $candidates.Add((Join-Path $env:ProgramFiles 'Steam\millennium')) }
    $SourceRoot = @($candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -Unique | Select-Object -First 1)[0]
    if (-not $SourceRoot) { throw 'millennium_source_not_found' }
}
function Invoke-Engine {
    param([string[]]$EngineArguments)
    $raw = & $PythonExecutable -I -B $engine @EngineArguments
    $code = $LASTEXITCODE
    try { $object = ($raw -join "`n") | ConvertFrom-Json -Depth 100 }
    catch { throw 'invalid_engine_response' }
    return [pscustomobject]@{ Code = $code; Value = $object }
}
$actions = @{Snapshot='snapshot';Status='status';Live='live';Verify='verify';Replicate='replicate';RestorePlan='restore-plan';Restore='restore';Rollback='rollback';Recover='recover'}
$arguments = @($actions[$Mode], '--destination', $destination)
if ($SourceRoot) { $arguments += @('--source', $SourceRoot) }
if ($Mode -in @('Snapshot','Status','Live') -or ($Mode -eq 'Replicate' -and $PSBoundParameters.ContainsKey('RuntimeRoot'))) { $arguments += @('--runtime',$RuntimeRoot) }
if ($TargetRoot) { $arguments += @('--target',$TargetRoot) }
if ($Mode -eq 'Snapshot') {
    $arguments += @('--keep',[string]$Keep)
    if ($AdoptExisting) { $arguments += '--adopt-existing' }
    $versions = @{}
    foreach ($pair in @(@('millennium',(Join-Path $SourceRoot 'lib\millennium.dll')),@('steam',(Join-Path (Split-Path -Parent $SourceRoot) 'steam.exe')))) {
        if (Test-Path -LiteralPath $pair[1] -PathType Leaf) { $versions[$pair[0]] = (Get-Item -LiteralPath $pair[1]).VersionInfo.FileVersion }
    }
    $arguments += @('--versions-json',($versions | ConvertTo-Json -Compress))
}
if ($ExpectedPlan) { $arguments += @('--expected-plan',$ExpectedPlan) }
if ($RollbackId) { $arguments += @('--rollback-id',$RollbackId) }
$result = Invoke-Engine $arguments
$exitCode = $result.Code
$payload = $result.Value
$payload | ConvertTo-Json -Depth 100
exit $exitCode
