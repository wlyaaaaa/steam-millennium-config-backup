Option Explicit
Dim fso, shell, here, repoRoot, command, engine, exitCode
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(here)
shell.CurrentDirectory = repoRoot
engine = shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\PowerShell\7\pwsh.exe"
If Not fso.FileExists(engine) Then WScript.Quit 2
command = """" & engine & """ -NoProfile -NonInteractive -File """ & here & "\Invoke-MillenniumBackup.ps1"" -Mode Snapshot -Json"
If WScript.Arguments.Count > 0 Then
    command = command & " -MachineConfig """ & Replace(WScript.Arguments(0), """", "") & """"
End If
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
