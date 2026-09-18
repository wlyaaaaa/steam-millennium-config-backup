Option Explicit
Dim fso, shell, here, engine, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
engine = shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\PowerShell\7\pwsh.exe"
If Not fso.FileExists(engine) Then WScript.Quit 2
command = """" & engine & """ -NoProfile -STA -File """ & here & "\Show-MillenniumBackupStatus.ps1"""
shell.Run command, 0, False
