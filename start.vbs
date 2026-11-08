' Starts the job tracker in the background, with no terminal window, and opens the browser
Set sh = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root & "\backend"
sh.Run """" & root & "\backend\.venv\Scripts\pythonw.exe"" run.py", 0, False
