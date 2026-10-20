#requires -Version 7.2
[CmdletBinding()]
param([string]$PythonExecutable=(Get-Command python.exe -ErrorAction Stop).Source)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$entry=Join-Path $repo 'tools\Invoke-MillenniumBackup.ps1'
$case=Join-Path $env:TEMP ('millennium-windows-'+[guid]::NewGuid().ToString('N'))
$source=Join-Path $case 'source';$destination=Join-Path $case 'destination'
$target=Join-Path $case 'target';$checks=0
function Assert-Case([bool]$Value,[string]$Name){if(-not $Value){throw "FAIL: $Name"};$script:checks++;Write-Host "PASS: $Name"}
function Invoke-Case([string]$Mode,[string[]]$Extra=@()){
 $a=@('-NoProfile','-NonInteractive','-File',$entry,'-Mode',$Mode,'-DestinationRoot',$destination,'-PythonExecutable',$PythonExecutable,'-Json')+$Extra
 $text=@(& pwsh @a);$code=$LASTEXITCODE
 [pscustomobject]@{code=$code;value=(($text -join "`n")|ConvertFrom-Json -Depth 100)}
}
function Signature([string]$Root){
 @((Get-ChildItem $Root -File -Recurse -Force|Sort-Object FullName)|ForEach-Object{ $_.FullName+':'+(Get-FileHash $_.FullName).Hash+':'+$_.LastWriteTimeUtc.Ticks }) -join "`n"
}
try{
 New-Item -ItemType Directory -Path $case|Out-Null
 & $PythonExecutable -I -B -c 'import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from test_backup import fixture;fixture(Path(sys.argv[2]));fixture(Path(sys.argv[3]))' (Join-Path $repo 'tests') $source $target
 if($LASTEXITCODE){throw 'fixture_failed'}
 $a=Invoke-Case Snapshot @('-SourceRoot',$source)
 Assert-Case ($a.code -eq 0 -and $a.value.status -eq 'complete') 'Windows wrapper produces a verified isolated snapshot'
 $a=Invoke-Case Snapshot @('-SourceRoot',$source)
 Assert-Case ($a.code -eq 0 -and $a.value.status -eq 'unchanged') 'Windows wrapper consecutive update does not self-lock'
 $before=Signature $destination
 $a=Invoke-Case Status @('-SourceRoot',$source)
 Assert-Case ($a.code -eq 0 -and $a.value.status -eq 'healthy') 'portable status does not depend on the live scheduled task'
 Assert-Case ((Signature $destination) -ceq $before) 'Windows status changes no snapshot or runtime bytes/timestamps'
 $a=Invoke-Case Verify
 Assert-Case ($a.code -eq 0 -and $a.value.status -eq 'verified') 'Windows Verify validates the manifest'
 $coldRoot=Join-Path $case 'cold'
 $a=Invoke-Case Replicate @('-TargetRoot',$coldRoot)
 if($a.code -ne 0){throw 'cold_fixture_replication_failed'}
 $receipt=Get-Content -LiteralPath (Join-Path $coldRoot 'replica-receipt.json') -Raw|ConvertFrom-Json
 $machine=Join-Path $case 'machine.json'
 @{schema='pcconfig.steam-millennium-backup.v1';machine_name=$env:COMPUTERNAME;project_root=$destination;source_root=$source;python_executable=$PythonExecutable;h_replica_root=$coldRoot;g_replica_enabled=$false}|ConvertTo-Json|Set-Content -LiteralPath $machine -Encoding utf8NoBOM
 $coldArgs=@('-SourceRoot',$source,'-MachineConfig',$machine)
 $a=Invoke-Case Status $coldArgs
 Assert-Case ($a.value.cold_replica.status -eq 'verified') 'cold replica with the current generation is verified'
 [IO.File]::AppendAllText((Join-Path $source 'config\quick.css'),"`nbody { opacity: 1; }")
 $a=Invoke-Case Snapshot @('-SourceRoot',$source)
 if($a.code -ne 0){throw 'new_generation_fixture_failed'}
 $before=(Signature $destination)+(Signature $coldRoot)
 $a=Invoke-Case Status $coldArgs
 Assert-Case ($a.value.cold_replica.status -eq 'verified_previous_generation' -and $a.value.cold_replica.local_generation -eq $a.value.generation -and $a.value.cold_replica.replica_generation -eq $receipt.generation -and $a.value.generation -ne $receipt.generation) 'valid older cold replica reports both generations without claiming corruption'
 Assert-Case ($a.value.cold_replica.last_attempt.generation -eq $receipt.generation -and $a.value.cold_replica.last_attempt.completed_utc -eq $receipt.completed_utc -and $a.value.cold_replica.last_attempt.status -eq $receipt.status) 'cold last attempt comes from its own replica receipt'
 Assert-Case (((Signature $destination)+(Signature $coldRoot)) -ceq $before) 'cold status changes no local or replica bytes/timestamps'
 [IO.File]::AppendAllText((Join-Path $coldRoot 'config\quick.css'),'corrupt')
 $a=Invoke-Case Status $coldArgs
 Assert-Case ($a.value.cold_replica.status -eq 'invalid' -and $a.value.cold_replica.readback.status -ne 'verified') 'corrupt cold replica is invalid even when its receipt reports complete'
 & $PythonExecutable -I -B -c 'import json,sys;from pathlib import Path;p=Path(sys.argv[1])/"config/config.json";v=json.loads(p.read_text());v["general"]["accentColor"]="blue";p.write_text(json.dumps(v),encoding="utf-8")' $target
 $original=(Get-FileHash (Join-Path $target 'config\config.json')).Hash
 $plan=Invoke-Case RestorePlan @('-TargetRoot',$target)
 Assert-Case ($plan.code -eq 0 -and $plan.value.status -eq 'ready') 'Windows restore preflight is ready in an isolated target'
 $a=Invoke-Case Restore @('-TargetRoot',$target,'-ExpectedPlan',$plan.value.plan_sha256)
 Assert-Case ($a.code -eq 0 -and $a.value.status -eq 'complete') 'Windows restore performs the expected plan'
 $raw=& pwsh -NoProfile -File $entry -Mode Rollback -DestinationRoot $target -RollbackId $a.value.rollback_id -PythonExecutable $PythonExecutable -Json
 Assert-Case ($LASTEXITCODE -eq 0 -and (Get-FileHash (Join-Path $target 'config\config.json')).Hash -ceq $original) 'Windows rollback recovers exact preimage bytes'
 $a=Invoke-Case Snapshot @('-SourceRoot',$source,'-RuntimeRoot',(Join-Path $source 'runtime'))
 Assert-Case ($a.code -ne 0 -and -not (Test-Path (Join-Path $source 'runtime'))) 'unsafe runtime overlap fails before creating source paths'
 $gui=& pwsh -NoProfile -STA -File (Join-Path $repo 'tools\Show-MillenniumBackupStatus.ps1') -ValidateOnly|ConvertFrom-Json
 Assert-Case ($LASTEXITCODE -eq 0 -and $gui.status -eq 'constructed' -and $gui.buttons -eq 5) 'status window constructs its five controls without launching a desktop window'
 [pscustomobject]@{schema='millennium.windows-tests.v1';status='passed';checks=$script:checks}|ConvertTo-Json
}finally{if(Test-Path $case){Remove-Item $case -Recurse -Force}}
