@echo off
setlocal
REM 入口在 launcher 根目录：任意盘符/路径放置本目录均可；调用 scripts 内 PS1（.env 与本文件同级）
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-CodexDesktop.ps1" -KillExisting
exit /b %ERRORLEVEL%
