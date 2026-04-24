@echo off
setlocal
REM 双击启动：%~dp0 为脚本所在目录，不依赖「当前工作目录」；路径含空格亦可用
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-CodexDesktop.ps1" -KillExisting
exit /b %ERRORLEVEL%
