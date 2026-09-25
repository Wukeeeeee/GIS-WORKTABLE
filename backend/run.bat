@echo off
REM ============================================================
REM  GIS-WORKTABLE Backend Dev Server (with Auto-Reload)
REM ============================================================
title GIS-WORKTABLE Backend (Dev)
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   GIS-WORKTABLE Backend Dev Server
echo   Listening on: http://127.0.0.1:8000
echo   Hot Reload: Enabled
echo ============================================================
echo.

"%PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
pause