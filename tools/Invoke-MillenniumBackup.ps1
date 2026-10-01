#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Snapshot','Status','Verify','Replicate','RestorePlan','Restore','Rollback','Recover')]
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
if (-not $MachineConfig -and $Mode -in @('Snapshot','Status') -and (Test-Path -LiteralPath $defaultMachine -PathType Leaf)) {
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
if (-not $SourceRoot -and $Mode -in @('Snapshot','Status')) {
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
$actions = @{Snapshot='snapshot';Status='status';Verify='verify';Replicate='replicate';RestorePlan='restore-plan';Restore='restore';Rollback='rollback';Recover='recover'}
$arguments = @($actions[$Mode], '--destination', $destination)
if ($SourceRoot) { $arguments += @('--source', $SourceRoot) }
if ($Mode -in @('Snapshot','Status') -or ($Mode -eq 'Replicate' -and $PSBoundParameters.ContainsKey('RuntimeRoot'))) { $arguments += @('--runtime',$RuntimeRoot) }
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
if ($Mode -eq 'Snapshot' -and $exitCode -eq 0 -and $config -and $config.g_replica_enabled) {
    try {
        # PCConfig is the volume identity owner. Never infer identity from G: alone.
        $core = Get-Content -LiteralPath $config.core_recovery_manifest -Raw | ConvertFrom-Json
        $set = @($core.backup_sets | Where-Object id -EQ $config.core_set_id)
        if ($set.Count -ne 1 -or $set[0].G_path -ne $config.g_replica_root) { throw 'replica_registration_mismatch' }
        $volume = @(Get-Volume -DriveLetter G -ErrorAction Stop)
        if ($volume.Count -ne 1) { throw 'g_volume_unavailable' }
        $identity = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes(([string]$volume[0].UniqueId).ToUpperInvariant()))).ToLowerInvariant()
        if ($identity -ne $core.backup_media.G.expected_volume_id_sha256 -or $volume[0].FileSystem -ne $core.backup_media.G.expected_filesystem -or $volume[0].FileSystemLabel -ne $core.backup_media.G.expected_label) { throw 'g_volume_identity_mismatch' }
        $replica = Invoke-Engine @('replicate','--destination',$destination,'--runtime',$RuntimeRoot,'--target',[string]$config.g_replica_root)
        if ($replica.Code -ne 0) { throw ('replica_failed:' + $replica.Value.reason) }
        $payload | Add-Member -NotePropertyName replica -NotePropertyValue $replica.Value -Force
        $payload | Add-Member -NotePropertyName file_warnings -NotePropertyValue @(@($payload.file_warnings) + @($replica.Value.file_warnings) | Where-Object { $null -ne $_ }) -Force
        # The engine owns durable, atomic JSON writes; no PowerShell serialization drift.
        & $PythonExecutable -I -B -c 'import os,pathlib,sys; p=pathlib.Path(sys.argv[2]); t=p.with_name(p.name+".tmp"); t.write_bytes(pathlib.Path(sys.argv[1]).read_bytes()); os.replace(t,p)' (Join-Path $config.g_replica_root 'replica-receipt.json') (Join-Path $RuntimeRoot 'replica-last.json')
        if ($LASTEXITCODE -ne 0) { throw 'replica_receipt_readback_failed' }
    }
    catch {
        $payload | Add-Member -NotePropertyName replica -NotePropertyValue @{status='failed';reason=$_.Exception.Message} -Force
        $payload.status = 'local_complete_replica_failed'
        $exitCode = 1
    }
}
if ($Mode -eq 'Snapshot' -and $config -and $result.Code -eq 0) {
    $runFile = Join-Path $RuntimeRoot 'machine-run.json'
    $runJson = $payload | ConvertTo-Json -Depth 100 -Compress
    $runJson | & $PythonExecutable -I -B -c 'import json,os,pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.with_name(p.name+".tmp"); d=json.loads(sys.stdin.read()); t.write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8"); os.replace(t,p)' $runFile
    if($LASTEXITCODE -ne 0){ throw 'machine_run_receipt_failed' }
}
if ($Mode -eq 'Status') {
    $payload | Add-Member -NotePropertyName health_scope -NotePropertyValue 'local_snapshot_task_and_hot_replica' -Force
    if($config){
        $coldPath=Join-Path ([string]$config.h_replica_root) 'replica-receipt.json'
        $cold=@{status='unverified_or_unavailable';expected_path=[string]$config.h_replica_root}
        if(Test-Path -LiteralPath $coldPath -PathType Leaf){
            try{
                $coldResult=Invoke-Engine @('verify','--destination',[string]$config.h_replica_root)
                $cold=@{status=if($coldResult.Code -eq 0 -and $coldResult.Value.generation -eq $payload.generation){'verified'}else{'stale_or_invalid'};readback=$coldResult.Value}
            }catch{$cold=@{status='unverified_or_unavailable';reason=$_.Exception.Message}}
        }
        $coldAttempt = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'PCConfig\core-recovery\cold-steam_millennium-last.json'
        if(Test-Path -LiteralPath $coldAttempt -PathType Leaf){
            try{$cold['last_attempt']=Get-Content -LiteralPath $coldAttempt -Raw|ConvertFrom-Json -Depth 20}catch{$cold['last_attempt']=@{status='unreadable'}}
        }
        $payload | Add-Member -NotePropertyName cold_replica -NotePropertyValue $cold -Force
    }
    $machineRun = Join-Path $RuntimeRoot 'machine-run.json'
    if ($config -and (Test-Path -LiteralPath $machineRun)) {
        $lastMachine = Get-Content -LiteralPath $machineRun -Raw | ConvertFrom-Json -Depth 100
        $payload | Add-Member -NotePropertyName machine_run -NotePropertyValue $lastMachine -Force
        if ($lastMachine.status -notin @('complete','unchanged')) {$payload.status='needs_attention';$exitCode=2}
    }
    if($config){ try {
        $task = Get-ScheduledTask -TaskName 'SteamMillenniumConfigSnapshot' -TaskPath '\' -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName 'SteamMillenniumConfigSnapshot' -TaskPath '\' -ErrorAction Stop
        $payload | Add-Member -NotePropertyName task -NotePropertyValue @{
            state=[string]$task.State;enabled=[bool]$task.Settings.Enabled;last_result=$info.LastTaskResult;
            last_run=$info.LastRunTime.ToString('o');next_run=$info.NextRunTime.ToString('o')
        } -Force
        if ((-not $task.Settings.Enabled -or $info.LastTaskResult -notin @(0,267009)) -and $payload.status -eq 'healthy') { $payload.status='needs_attention'; $exitCode=2 }
    }
    catch { $payload | Add-Member -NotePropertyName task -NotePropertyValue @{state='unknown_or_missing'} -Force; if ($config) {$payload.status='needs_attention';$exitCode=2} } }
    if ($config -and $config.g_replica_enabled) {
        try {
            $r = Invoke-Engine @('verify','--destination',[string]$config.g_replica_root)
            $payload | Add-Member -NotePropertyName replica_readback -NotePropertyValue $r.Value -Force
            $warningProjection = $null -ne $lastMachine -and $lastMachine.replica.status -eq 'complete' -and
                @($lastMachine.replica.file_warnings).Count -gt 0 -and
                $lastMachine.replica.source_generation -eq $payload.generation -and
                $lastMachine.replica.generation -eq $r.Value.generation
            if ($r.Code -ne 0 -or ($r.Value.generation -ne $payload.generation -and -not $warningProjection)) { $payload.status='needs_attention';$exitCode=2 }
            elseif($warningProjection){ $payload | Add-Member -NotePropertyName file_warnings -NotePropertyValue $lastMachine.file_warnings -Force }
        }
        catch { $payload | Add-Member -NotePropertyName replica_readback -NotePropertyValue @{status='unavailable'} -Force;$payload.status='needs_attention';$exitCode=2 }
    }
}
$payload | ConvertTo-Json -Depth 100
exit $exitCode
