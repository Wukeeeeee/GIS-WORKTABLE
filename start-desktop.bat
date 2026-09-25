@echo off
REM ============================================================
REM  GIS-WORKTABLE Desktop Launcher
REM ============================================================
title GIS-WORKTABLE Desktop Launcher
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ============================================
echo    GIS-WORKTABLE Desktop Client
echo  ============================================
echo.

REM ---- 1. Check Port 8000 & Backend ----
set "PORT=8000"
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo  [OK] Backend already running on port %PORT%.
  goto launch_desktop
)

echo  [INFO] Starting backend on port %PORT%...
set "PY="
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  [ERROR] Python not found. Please install Python 3.10+.
  pause
  exit /b 1
)

start "GIS-WORKTABLE Backend" /min "%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%

set /a "RETRIES=0"
:wait_backend_loop
timeout /t 1 /nobreak >nul
set /a "RETRIES+=1"
curl.exe -s "http://127.0.0.1:%PORT%/api/health" 2>nul | findstr jigsaw >nul
if not errorlevel 1 goto launch_desktop
if %RETRIES% LSS 15 goto wait_backend_loop
echo  [WARNING] Backend health check timeout, attempting to launch desktop anyway...

:launch_desktop
set "ELECTRON_EXE=%~dp0desktop\node_modules\electron\dist\electron.exe"
if exist "%ELECTRON_EXE%" (
  echo  [OK] Launching GIS-WORKTABLE Desktop App...
  start "" "%ELECTRON_EXE%" "%~dp0desktop"
  exit /b 0
)

echo  [INFO] Local Electron binary not found, attempting npm start in desktop/...
if exist "%~dp0desktop\package.json" (
  cd /d "%~dp0desktop"
  npm start
  exit /b 0
)

echo  [ERROR] desktop/ directory not found.
pause
exit /b 1