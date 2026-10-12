@echo off
setlocal
title GIS-WORKTABLE Launcher
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
if defined GIS_PYTHON set "PY=%GIS_PYTHON%"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"

set "PORT="
for /f "delims=" %%p in ('call "%PY%" -m backend.launcher select') do set "PORT=%%p"
if not defined PORT (
  echo [ERROR] Cannot select a backend port. Check Python and GIS_PORT.
  pause
  exit /b 1
)
"%PY%" -m backend.launcher check --port %PORT%
if errorlevel 1 (
  echo Starting GIS-WORKTABLE on port %PORT%...
  start "GIS-WORKTABLE Backend" "%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%
)
"%PY%" -m backend.launcher wait --port %PORT%
if errorlevel 1 (
  pause
  exit /b 1
)
echo GIS-WORKTABLE: http://127.0.0.1:%PORT%
start "" "http://127.0.0.1:%PORT%"
echo To stop: Ctrl+C in the backend window, or run scripts\stop.bat.
