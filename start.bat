@echo off
REM ============================================================
REM  GIS-WORKTABLE Launcher
REM  One-click start for backend + browser
REM ============================================================
title GIS-WORKTABLE Launcher
chcp 65001 >nul
cd /d "%~dp0"

cls
echo.
echo  ============================================
echo    GIS-WORKTABLE
echo    Intelligent GIS Work Platform
echo  ============================================
echo.
echo  [1/4] Checking Python environment...

REM ---- Find Python ----
set "PY="
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  [ERROR] Python not found.
  echo  Please install Python 3.10 or higher from https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
echo        Python found: %PY%

REM ---- Port ----
set "PORT=8000"
if not "%GIS_PORT%"=="" set "PORT=%GIS_PORT%"

echo.
echo  [2/4] Checking port %PORT%...

REM ---- Check port ----
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo        Port %PORT% is already in use.
  echo        Service may be running already.
  echo.
  echo  [3/4] Opening browser...
  start "" "http://127.0.0.1:%PORT%"
  echo.
  echo  ============================================
  echo   Ready! Open http://127.0.0.1:%PORT% in your browser.
  echo   Close this window will NOT stop the backend.
  echo   To stop backend: press Ctrl+C in backend window.
  echo  ============================================
  echo.
  pause
  exit /b 0
)
echo        Port %PORT% is available.

echo.
echo  [3/4] Starting backend...
echo        This may take a few seconds on first run.
echo.

REM ---- Start backend in new window ----
start "GIS-WORKTABLE Backend" "%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%

REM ---- Wait for server to be ready ----
set /a "RETRIES=0"
:wait_loop
timeout /t 1 /nobreak >nul
set /a "RETRIES+=1"
curl -s -o nul -w "%%{http_code}" "http://127.0.0.1:%PORT%/api/health" 2>nul | findstr "200" >nul
if not errorlevel 1 goto server_ready
if %RETRIES% LSS 15 goto wait_loop

echo  [WARNING] Server did not respond within 15 seconds.
echo  Please check the backend window for error messages.
echo.
pause
exit /b 1

:server_ready
echo.
echo  [4/4] Server is running! Opening browser...
start "" "http://127.0.0.1:%PORT%"

echo.
echo  ============================================
echo   GIS-WORKTABLE is running!
echo   URL: http://127.0.0.1:%PORT%
echo.
echo   Backend runs in a separate window.
echo   Close this window - backend keeps running.
echo   To stop: press Ctrl+C in backend window,
echo           or close the backend window.
echo  ============================================
echo.
pause
