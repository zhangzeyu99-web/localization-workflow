@echo off
REM 双击启动：调用 PowerShell 封装（路径含空格时更稳）
set SCRIPT=%~dp0Start-CodexDesktop.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -KillExisting
exit /b %ERRORLEVEL%
