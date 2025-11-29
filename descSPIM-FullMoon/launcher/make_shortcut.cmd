@echo off

rem ---- run_app.bat を生成 ----
echo @echo off > "%~dp0run_app.bat"
echo cd /d "%%~dp0\.." >> "%~dp0run_app.bat"
echo .myenv-descSPIM-Fullmoon\Scripts\python Main.py >> "%~dp0run_app.bat"

rem ----（ここから下がショートカット生成処理）----
set "TARGET=%~dp0run_app.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\descSPIM-Fullmoon.lnk"
set "ICON=%~dp0descSPIM.ico"
set "VBS=%TEMP%\_tmp_descspim_%RANDOM%.vbs"

> "%VBS%" echo Set oWS = WScript.CreateObject("WScript.Shell")
>> "%VBS%" echo Set lnk = oWS.CreateShortcut("%SHORTCUT%")
>> "%VBS%" echo lnk.TargetPath = "%TARGET%"
>> "%VBS%" echo lnk.WorkingDirectory = "%~dp0\.."
>> "%VBS%" echo lnk.IconLocation = "%ICON%"
>> "%VBS%" echo lnk.WindowStyle = 1
>> "%VBS%" echo lnk.Save

cscript //nologo "%VBS%"
del "%VBS%"

echo ショートカットを作成しました:
echo   %SHORTCUT%
pause
