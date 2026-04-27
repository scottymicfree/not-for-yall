Dim fso, shell, scriptDir, batPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(scriptDir, "START_LUCY.bat")
shell.Run Chr(34) & batPath & Chr(34), 0
Set shell = Nothing
Set fso = Nothing
