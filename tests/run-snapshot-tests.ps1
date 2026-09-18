#requires -Version 7.2
[CmdletBinding()]
param([string]$PythonExecutable='')
$ErrorActionPreference='Stop'
if(-not $PythonExecutable){$PythonExecutable=(Get-Command python.exe -ErrorAction Stop).Source}
$taskRoot='E:\Cache\Codex\Temp\millennium-tests-'+[guid]::NewGuid().ToString('N')
if(-not(Test-Path 'E:\')){$taskRoot=Join-Path ([IO.Path]::GetTempPath()) ('millennium-tests-'+[guid]::NewGuid().ToString('N'))}
$old=@{TEMP=$env:TEMP;TMP=$env:TMP;TMPDIR=$env:TMPDIR}
New-Item -ItemType Directory -Force -Path $taskRoot|Out-Null
try{
    $env:TEMP=$taskRoot;$env:TMP=$taskRoot;$env:TMPDIR=$taskRoot
    & $PythonExecutable -I -B (Join-Path $PSScriptRoot 'test_backup.py')
    $code=$LASTEXITCODE
    if($code -ne 0){throw "snapshot_tests_failed:$code"}
    if($IsWindows){ & (Join-Path $PSScriptRoot 'run-windows-tests.ps1') -PythonExecutable $PythonExecutable }
}finally{
    $env:TEMP=$old.TEMP;$env:TMP=$old.TMP;$env:TMPDIR=$old.TMPDIR
    Remove-Item -LiteralPath $taskRoot -Recurse -Force
}
