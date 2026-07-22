Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get directory of current script
strScriptPath = fso.GetParentFolderName(Wscript.ScriptFullName)
WshShell.CurrentDirectory = strScriptPath

' Check if site-packages is extracted
If Not fso.FolderExists("python\site-packages") Then
    ' Run tar to extract site-packages.zip silently (0 = hide window, True = wait for completion)
    WshShell.Run "tar -xf python\site-packages.zip -C python", 0, True
End If

' Run pythonw.exe in background (0 hides the console window)
WshShell.Run "python\pythonw.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000", 0, False

' Wait 2 seconds for server startup
Wscript.Sleep 2000

' Open the user's default web browser
WshShell.Run "cmd /c start http://127.0.0.1:8000/", 0, False
