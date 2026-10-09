@echo off
setlocal
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found.
  pause
  exit /b 1
)
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-worker.ps1"
