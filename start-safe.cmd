@echo off
powershell.exe -NoProfile -File "%~dp0start-safe.ps1" %*
exit /b %ERRORLEVEL%
