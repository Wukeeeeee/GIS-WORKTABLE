@echo off
setlocal
title GIS-WORKTABLE Launcher
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1"
if errorlevel 1 (
  pause
  exit /b 1
)
set "PY="
if exist "%~dp0.bootstrap\python-path.txt" (
  set /p "PY=" < "%~dp0.bootstrap\python-path.txt"
)
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  echo [ERROR] Python setup did not return a runtime path.
  pause
  exit /b 1
)

set "PORT="
for /f "delims=" %%p in ('call "%PY%" -m backend.launcher select') do set "PORT=%%p"
if not defined PORT (
  echo [ERROR] Cannot select a backend port. Check Python and GIS_PORT.
  pause
  exit /b 1
)

call "%PY%" -m backend.launcher start --port %PORT%
if errorlevel 1 (
  pause
  exit /b 1
)

echo GIS-WORKTABLE: http://127.0.0.1:%PORT%
call "%PY%" -m backend.launcher open-browser --port %PORT%
echo To stop: Ctrl+C in the backend window, or run stop.bat.
