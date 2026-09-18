[CmdletBinding()]
param([string]$TaskName='SteamMillenniumConfigSnapshot',[string]$RepoRoot=(Split-Path -Parent $PSScriptRoot),[string]$MachineConfig='',[ValidateSet('Inspect','Install','Enable','Disable')][string]$Mode='Install')
$pwsh=Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'
$argsList=@('-NoProfile','-NonInteractive','-File',(Join-Path $PSScriptRoot 'Manage-MillenniumTask.ps1'),'-Mode',$Mode,'-TaskName',$TaskName,'-RepoRoot',$RepoRoot,'-Json')
if($MachineConfig){$argsList+=@('-MachineConfig',$MachineConfig)}
& $pwsh @argsList
exit $LASTEXITCODE
