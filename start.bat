@echo off
REM ============================================================
REM  GIS-WORKTABLE 一键启动脚本（Windows）
REM  双击本文件即可启动后端 + 自动打开浏览器
REM  停止：在后端窗口按 Ctrl+C
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ============================================
echo    GIS-WORKTABLE 一键启动
echo  ============================================
echo.

REM ---- 自动寻找 Python ----
set "PY="
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  [错误] 未找到 Python 环境。
  echo  请安装 Python 3.10+，或在脚本顶部手动设置 PY 变量路径。
  echo.
  pause
  exit /b 1
)

REM ---- 端口（可用环境变量覆盖，默认 8000）----
set "PORT=8000"
if not "%GIS_PORT%"=="" set "PORT=%GIS_PORT%"

echo  使用 Python : %PY%
echo  服务地址    : http://localhost:%PORT%
echo  停止服务    : 在后端窗口按 Ctrl+C
echo.

REM ---- 检查端口是否被占用 ----
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo  [提示] 端口 %PORT% 已被占用，可能服务已在运行。
  echo  直接打开浏览器访问 http://localhost:%PORT%
  start "" "http://localhost:%PORT%"
  pause
  exit /b 0
)

REM ---- 启动后端（新窗口）并打开浏览器 ----
start "GIS-WORKTABLE 后端" "%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
timeout /t 4 /nobreak >nul
start "" "http://localhost:%PORT%"

echo  已启动，浏览器即将打开。
echo  如果未自动打开，请手动访问 http://localhost:%PORT%
echo.
pause
