[CmdletBinding()]
param(
    [string]$SourceRoot='', [string]$DestinationRoot='', [string]$RuntimeRoot='',
    [int]$ThrottleDays=0, [switch]$Force, [switch]$AllowDirtyDestination,
    [switch]$AdoptExisting, [string]$MachineConfig=''
)
# Compatibility entry: old Force/ThrottleDays no longer suppress verification.
# AllowDirtyDestination can no longer bypass actual snapshot conflicts.
$entry = Join-Path $PSScriptRoot 'Invoke-MillenniumBackup.ps1'
$argsList = @('-NoProfile','-NonInteractive','-File',$entry,'-Mode','Snapshot','-Json')
foreach($name in @('SourceRoot','DestinationRoot','RuntimeRoot','MachineConfig')) {
    if (Get-Variable -Name $name -ValueOnly) { $argsList += @(('-'+$name),(Get-Variable -Name $name -ValueOnly)) }
}
if($AdoptExisting){$argsList += '-AdoptExisting'}
$pwsh = Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'
if (-not (Test-Path -LiteralPath $pwsh)) { throw 'PowerShell 7.2+ is required.' }
& $pwsh @argsList
exit $LASTEXITCODE
