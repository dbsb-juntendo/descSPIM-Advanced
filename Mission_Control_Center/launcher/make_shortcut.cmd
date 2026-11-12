@echo off

rem --- User settings: adjust these paths for the installation PC. ---
rem Python executable: relative to the MCC folder (parent of launcher),
rem or an absolute path. The generated launcher runs from the MCC folder.
set "MCC_PYTHON_EXE=.myenv-descSPIM-MCC\Scripts\python.exe"
rem Existing folder where the shortcut will be saved. This path is used
rem as configured; the script does not discover the Windows Desktop location.
set "MCC_SHORTCUT_DIR=%USERPROFILE%\Desktop"

echo @echo off > "%~dp0run_app.bat"
echo cd /d "%%~dp0\.." >> "%~dp0run_app.bat"
echo "%MCC_PYTHON_EXE%" "Main.py" >> "%~dp0run_app.bat"

set "TARGET=%~dp0run_app.bat"
set "SHORTCUT=%MCC_SHORTCUT_DIR%\descSPIM-MCC.lnk"
set "ICON=%~dp0MCC.ico"
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

echo Shortcut has been created:
echo   %SHORTCUT%
pause
