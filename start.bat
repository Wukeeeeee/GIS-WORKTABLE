@echo off
REM ============================================================
REM  GIS-WORKTABLE Quick Start Script (Windows)
REM  Double-click to start backend and open browser
REM  Stop: Press Ctrl+C in the backend window
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ============================================
echo    GIS-WORKTABLE Quick Start
echo  ============================================
echo.

REM ---- Find Python ----
set "PY="
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  [ERROR] Python not found.
  echo  Please install Python 3.10+ or set PY path manually.
  echo.
  pause
  exit /b 1
)

REM ---- Port (override with GIS_PORT env var, default 8000) ----
set "PORT=8000"
if not "%GIS_PORT%"=="" set "PORT=%GIS_PORT%"

echo  Python : %PY%
echo  URL    : http://localhost:%PORT%
echo  Stop   : Press Ctrl+C in backend window
echo.

REM ---- Check if port is in use ----
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo  [INFO] Port %PORT% is already in use. Service may be running.
  echo  Opening browser at http://localhost:%PORT%
  start "" "http://localhost:%PORT%"
  pause
  exit /b 0
)

REM ---- Start backend (new window) and open browser ----
start "GIS-WORKTABLE Backend" "%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
timeout /t 4 /nobreak >nul
start "" "http://localhost:%PORT%"

echo  Started. Browser will open shortly.
echo  If not, please visit http://localhost:%PORT% manually.
echo.
pause
