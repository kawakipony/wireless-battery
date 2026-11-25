' 静默启动脚本：在后台运行托盘程序，不弹出任何命令行黑框
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "pythonw.exe """ & baseDir & "\run.pyw"""
shell.Run cmd, 0, False
