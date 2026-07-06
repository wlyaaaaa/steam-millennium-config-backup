' Hidden launcher for the Steam Millennium config snapshot task.
Dim fso, shell, here, repoRoot, command, exitCode

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(here)
shell.CurrentDirectory = repoRoot
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & here & "\snapshot-millennium-config.ps1"""
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
