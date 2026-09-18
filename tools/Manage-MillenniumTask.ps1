#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Inspect','Install','Enable','Disable')][string]$Mode='Inspect',
    [string]$TaskName='SteamMillenniumConfigSnapshot',
    [string]$RepoRoot=(Split-Path -Parent $PSScriptRoot),
    [string]$MachineConfig='',
    [switch]$Json
)
$ErrorActionPreference='Stop'
$defaultMachine='E:\PCConfig\registries\steam_millennium_backup.json'
if(-not $MachineConfig -and (Test-Path -LiteralPath $defaultMachine -PathType Leaf)){
    $candidate=Get-Content -LiteralPath $defaultMachine -Raw|ConvertFrom-Json
    if($candidate.project_root -eq [IO.Path]::GetFullPath($RepoRoot) -and $candidate.machine_name -eq $env:COMPUTERNAME){$MachineConfig=$defaultMachine}
}
$taskPath='\'
$launcher=Join-Path $RepoRoot 'tools\snapshot-millennium-config-hidden.vbs'
$entry=Join-Path $RepoRoot 'tools\Invoke-MillenniumBackup.ps1'
$pwsh=Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'
$wscript=Join-Path $env:WINDIR 'System32\wscript.exe'
$arguments='"'+$launcher+'"'
if($MachineConfig){$arguments+=' "'+[IO.Path]::GetFullPath($MachineConfig)+'"'}
$currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$task=Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -ErrorAction SilentlyContinue
$ownerTag='owner=steam-millennium-config-backup;'
if($Mode -ne 'Inspect'){
    if($currentSid -eq 'S-1-5-18'){throw 'Register from the intended interactive user, not SYSTEM.'}
    if($task -and $task.Description -notlike "$ownerTag*" -and $task.Description -notlike 'Low-frequency allowlisted Steam Millennium config snapshot.*'){
        throw 'Existing task is not owned by this project.'
    }
}
if($Mode -eq 'Install'){
    foreach($p in @($launcher,$entry,$pwsh,$wscript)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw "dependency_missing:$p"}}
    if($MachineConfig -and -not(Test-Path -LiteralPath $MachineConfig -PathType Leaf)){throw 'machine_config_missing'}
    $oldXml=if($task){Export-ScheduledTask -TaskName $TaskName -TaskPath $taskPath}else{$null}
    try{
        $action=New-ScheduledTaskAction -Execute $wscript -Argument $arguments -WorkingDirectory $RepoRoot
        $trigger=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '19:30'
        $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $principal=New-ScheduledTaskPrincipal -UserId $currentSid -LogonType Interactive -RunLevel Limited
        $definition=New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description ($ownerTag+' Verified weekly configuration snapshot and registered G replica. Manage/stop in Task Scheduler; disabling only stops backups, not Steam. Status: tools\Show-MillenniumBackupStatus.ps1')
        Register-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -InputObject $definition -Force | Out-Null
    }catch{
        if($oldXml){Register-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Xml $oldXml -Force | Out-Null}
        throw
    }
}elseif($Mode -eq 'Enable'){
    Enable-ScheduledTask -TaskName $TaskName -TaskPath $taskPath | Out-Null
}elseif($Mode -eq 'Disable'){
    # Do not terminate an in-flight transaction; only suppress future triggers.
    Disable-ScheduledTask -TaskName $TaskName -TaskPath $taskPath | Out-Null
}
$task=Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -ErrorAction SilentlyContinue
if(-not $task){@{schema='millennium.task.v2';status='missing';write_mode='zero_write'}|ConvertTo-Json;exit 2}
$info=Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $taskPath
$issues=[Collections.Generic.List[string]]::new()
if(@($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ne $wscript -or $task.Actions[0].Arguments -ne $arguments -or $task.Actions[0].WorkingDirectory -ne $RepoRoot){$issues.Add('action_mismatch')}
if($task.Description -notlike "$ownerTag*"){$issues.Add('owner_marker_mismatch')}
$t=@($task.Triggers)
if($t.Count -ne 1 -or $t[0].CimClass.CimClassName -ne 'MSFT_TaskWeeklyTrigger' -or $t[0].DaysOfWeek -ne 1 -or $t[0].WeeksInterval -ne 1 -or -not $t[0].Enabled){$issues.Add('trigger_mismatch')}
elseif(([datetime]$t[0].StartBoundary).TimeOfDay -ne [timespan]::FromHours(19.5)){$issues.Add('schedule_mismatch')}
if([string]$task.Principal.LogonType -ne 'Interactive' -or [string]$task.Principal.RunLevel -ne 'Limited'){$issues.Add('principal_mismatch')}
$principalSid=try{([Security.Principal.NTAccount]::new([string]$task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value}catch{[string]$task.Principal.UserId}
if($principalSid -ne $currentSid){$issues.Add('user_mismatch')}
if($task.Settings.ExecutionTimeLimit -ne 'PT10M' -or $task.Settings.RestartCount -ne 3 -or $task.Settings.RestartInterval -ne 'PT15M' -or [string]$task.Settings.MultipleInstances -ne 'IgnoreNew' -or -not $task.Settings.StartWhenAvailable){$issues.Add('settings_mismatch')}
if($Mode -eq 'Install' -and $issues.Count -gt 0){
    if($oldXml){Register-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Xml $oldXml -Force|Out-Null}
    else{Unregister-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Confirm:$false}
    throw ('installation_readback_failed:'+($issues -join ','))
}
if($Mode -eq 'Install'){
    $statusLauncher=Join-Path $RepoRoot 'tools\show-millennium-backup-status.vbs'
    if(-not(Test-Path -LiteralPath $statusLauncher -PathType Leaf)){throw 'status_launcher_missing'}
    $link=Join-Path ([Environment]::GetFolderPath('Programs')) 'Steam Millennium 备份状态.lnk'
    $shell=New-Object -ComObject WScript.Shell
    $shortcut=$shell.CreateShortcut($link)
    if((Test-Path -LiteralPath $link) -and $shortcut.Arguments -notlike '*show-millennium-backup-status.vbs*'){throw 'unrelated_shortcut_preserved'}
    $shortcut.TargetPath=$wscript
    $shortcut.Arguments='"'+$statusLauncher+'"'
    $shortcut.WorkingDirectory=$RepoRoot
    $shortcut.Description='检查、备份和管理 Steam Millennium 配置快照'
    $shortcut.IconLocation=(Join-Path $env:WINDIR 'System32\shell32.dll')+',46'
    $shortcut.Save()
    $readback=$shell.CreateShortcut($link)
    if($readback.TargetPath -ne $wscript -or $readback.Arguments -ne $shortcut.Arguments){throw 'shortcut_readback_failed'}
}
@{schema='millennium.task.v2';status=if($issues.Count){'drift'}else{'verified'};issues=@($issues);task_name=$TaskName;task_path=$taskPath;enabled=[bool]$task.Settings.Enabled;state=[string]$task.State;last_result=$info.LastTaskResult;last_run=$info.LastRunTime.ToString('o');next_run=$info.NextRunTime.ToString('o');write_mode=if($Mode -eq 'Inspect'){'zero_write'}else{'task_configuration'}}|ConvertTo-Json -Depth 6
if($issues.Count){exit 2}
