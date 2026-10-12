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
if exist "%~dp0..\desktop\package.json" (
  cd /d "%~dp0..\desktop"
  npm start
  exit /b 0
)

echo  [ERROR] desktop/ directory not found.
pause
exit /b 1