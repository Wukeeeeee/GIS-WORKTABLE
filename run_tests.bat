@echo off
REM ============================================================
REM  GIS-WORKTABLE Test Suite Runner
REM ============================================================
title Run GIS-WORKTABLE Tests
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
echo  Running backend test suite (366+ tests)...
echo.
"%PY%" -m pytest backend/tests/ -q

if %errorlevel% neq 0 (
  echo.
  echo  [FAIL] Some tests failed!
  pause
  exit /b %errorlevel%
)

echo.
echo  [PASS] All tests passed successfully!
echo.
pause