@echo off
REM ============================================================
REM  GIS-WORKTABLE Desktop Launcher
REM ============================================================
title GIS-WORKTABLE Desktop Launcher
chcp 65001 >nul
cd /d "%~dp0.."

echo.
echo  ============================================
echo    GIS-WORKTABLE Desktop Client
echo  ============================================
echo.

REM Electron manages backend identity, port selection and startup.
set "ELECTRON_EXE=%~dp0..\desktop\node_modules\electron\dist\electron.exe"
if exist "%ELECTRON_EXE%" (
  echo  [OK] Launching GIS-WORKTABLE Desktop App...
  start "" "%ELECTRON_EXE%" "%~dp0..\desktop"
  exit /b 0
)

echo  [INFO] Local Electron binary not found, attempting npm start in desktop/...
if not exist "%~dp0..\desktop\package.json" goto missing_desktop
cd /d "%~dp0..\desktop"
call npm start
exit /b %ERRORLEVEL%

:missing_desktop
echo  [ERROR] desktop/ directory not found.
pause
exit /b 1
