@echo off
setlocal
title Stop GIS-WORKTABLE
chcp 65001 >nul
cd /d "%~dp0.."
set "PY="
if exist "%~dp0..\.bootstrap\python-path.txt" (
  set /p "PY=" < "%~dp0..\.bootstrap\python-path.txt"
)
if not defined PY if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
if not defined PY if defined GIS_PYTHON set "PY=%GIS_PYTHON%"
if not defined PY set "PY=python"
"%PY%" -m backend.launcher stop
if errorlevel 1 pause
