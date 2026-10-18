' GUI host: hide the console at process creation, before PowerShell can run.
' Wait and propagate the child exit code so Task Scheduler retains its result.
Option Explicit

Dim shell, encoded, validation, command, result
If WScript.Arguments.Count <> 1 Then WScript.Quit 64
encoded = WScript.Arguments(0)
Set validation = New RegExp
validation.Pattern = "^[A-Za-z0-9+/]+={0,2}$"
If Len(encoded) = 0 Or Len(encoded) > 24000 Then WScript.Quit 64
If Not validation.Test(encoded) Then WScript.Quit 64

Set shell = CreateObject("WScript.Shell")
command = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%") & _
    "\System32\WindowsPowerShell\v1.0\powershell.exe" & Chr(34) & _
    " -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand " & encoded
result = shell.Run(command, 0, True)
WScript.Quit result
