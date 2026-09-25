@echo off
REM ============================================================
REM  GIS-WORKTABLE Service Terminator
REM  Stops backend process listening on port 8000
REM ============================================================
title Stop GIS-WORKTABLE
chcp 65001 >nul
cd /d "%~dp0"

set "PORT=8000"
echo.
echo  Checking services on port %PORT%...
echo.

set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo  Stopping process with PID: %%a on port %PORT%
  taskkill /F /PID %%a >nul 2>&1
)

if "%FOUND%"=="1" (
  echo.
  echo  [OK] Port %PORT% service terminated successfully.
) else (
  echo  [INFO] No active service found on port %PORT%.
)

echo.
timeout /t 2 >nul