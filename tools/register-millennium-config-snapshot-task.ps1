[CmdletBinding()]
param(
    [string] $TaskName = 'SteamMillenniumConfigSnapshot',
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

$snapshotScript = Join-Path $RepoRoot 'tools\snapshot-millennium-config.ps1'
$snapshotLauncher = Join-Path $RepoRoot 'tools\snapshot-millennium-config-hidden.vbs'
if (-not (Test-Path -LiteralPath $snapshotScript -PathType Leaf)) {
    throw "Snapshot script not found: $snapshotScript"
}
if (-not (Test-Path -LiteralPath $snapshotLauncher -PathType Leaf)) {
    throw "Snapshot launcher not found: $snapshotLauncher"
}

$action = New-ScheduledTaskAction `
    -Execute 'wscript.exe' `
    -Argument ('"{0}"' -f $snapshotLauncher) `
    -WorkingDirectory $RepoRoot

$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 19:30

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $weeklyTrigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Low-frequency allowlisted Steam Millennium config snapshot. Copies only public-safe JSON/CSS config files.'

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName
