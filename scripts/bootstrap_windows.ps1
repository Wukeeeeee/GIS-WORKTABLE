# UTF-8 with BOM for Windows PowerShell 5.1 compatibility
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bootstrapDir = Join-Path $projectRoot '.bootstrap'
$venvDir = Join-Path $projectRoot '.venv'
$runtimePython = Join-Path $venvDir 'Scripts\python.exe'
$checker = Join-Path $PSScriptRoot 'check_runtime.py'
$lockPath = Join-Path $bootstrapDir 'bootstrap.lock'
$lockStream = $null

function Test-Python([string]$candidate) {
    if (-not $candidate) { return $false }
    try {
        & $candidate -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) and sys.maxsize > 2**32 else 1)' | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Save-Runtime {
    [IO.File]::WriteAllText((Join-Path $bootstrapDir 'python-path.txt'), $runtimePython, [Text.UTF8Encoding]::new($false))
}

function Backup-And-Reset-Venv([string]$reason) {
    Write-Host "[WARN] $reason" -ForegroundColor Yellow
    if (Test-Path -LiteralPath $venvDir) {
        $backup = [IO.Path]::GetFullPath((Join-Path $bootstrapDir ('old-venv-' + [Guid]::NewGuid().ToString('N'))))
        Write-Host "[BACKUP] Moving invalid .venv to: $backup" -ForegroundColor Yellow
        try {
            Move-Item -LiteralPath $venvDir -Destination $backup -Force
        } catch {
            throw "Cannot safely back up .venv; close processes using it and retry. $($_.Exception.Message)"
        }
    }
}

try {
    Set-Location -LiteralPath $projectRoot
    New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null

    # Concurrency guard: Acquire exclusive bootstrap lock to prevent concurrent double-click corruption
    $lockAcquired = $false
    $lockDeadline = (Get-Date).AddMinutes(10)
    while (-not $lockAcquired) {
        try {
            $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $lockAcquired = $true
        } catch {
            if ((Get-Date) -gt $lockDeadline) { throw 'Timed out waiting for concurrent setup process to finish.' }
            Write-Host '[WAIT] Another installation or setup process is running. Waiting for it to finish...'
            Start-Sleep -Seconds 2
        }
    }

    Write-Host '[1/3] Checking the local Python environment...'
    if (Test-Path -LiteralPath $venvDir) {
        if (-not (Test-Python $runtimePython)) {
            Backup-And-Reset-Venv 'Detected copied or broken .venv (interpreter cannot run). Rebuilding fresh environment...'
        } else {
            & $runtimePython $checker
            if ($LASTEXITCODE -eq 0) {
                Save-Runtime
                Write-Host '[READY] Existing environment is ready. No download needed.'
                exit 0
            }
            Write-Host '[INFO] Existing .venv has missing or outdated packages. Repairing...'
        }
    }

    # Locate or prepare uv
    $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
    $uvExe = Join-Path $bootstrapDir 'uv.exe'
    if ($uvCommand) { $uvExe = $uvCommand.Source }
    if (-not (Test-Path -LiteralPath $uvExe)) {
        Write-Host '[DOWNLOAD] Preparing the local dependency installer (uv 0.13.1)...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $archive = Join-Path $bootstrapDir 'uv.zip'
        $uvUrls = @(
            'https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip',
            'https://ghproxy.net/https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip'
        )
        $uvSuccess = $false
        foreach ($url in $uvUrls) {
            try {
                Write-Host "  Trying: $url"
                Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive -TimeoutSec 25
                if ((Test-Path -LiteralPath $archive) -and (Get-Item -LiteralPath $archive).Length -gt 100000) {
                    Expand-Archive -LiteralPath $archive -DestinationPath $bootstrapDir -Force
                    if (Test-Path -LiteralPath $uvExe) {
                        $uvSuccess = $true
                        break
                    }
                }
            } catch {
                Write-Host "  Could not download from: $url"
            }
        }
        if (-not $uvSuccess) {
            Write-Host ''
            Write-Host '[ERROR] 无法从 GitHub 下载依赖安装工具 (uv)。' -ForegroundColor Red
            Write-Host '说明：国内网络环境下直连 GitHub Releases 容易超时或被阻断。' -ForegroundColor Yellow
            Write-Host ''
            Write-Host '【解决办法（三选一）】:' -ForegroundColor Cyan
            Write-Host '  1. 手动下载 uv (Windows 64位):'
            Write-Host '     下载链接: https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip'
            Write-Host '     解压得到 uv.exe，放入本项目的 .bootstrap\ 目录下 (即 .bootstrap\uv.exe)。'
            Write-Host '  2. 若系统已安装任意 Python，可在终端运行: pip install uv'
            Write-Host '  3. 配置网络代理使命令行能访问 GitHub 后重新运行 start.bat。'
            Write-Host ''
            throw 'Cannot download uv from GitHub. Please install uv manually or place uv.exe into .bootstrap directory.'
        }
    }

    $env:UV_PYTHON_INSTALL_DIR = Join-Path $bootstrapDir 'python'
    $env:UV_CACHE_DIR = Join-Path $bootstrapDir 'cache'
    $env:PYTHONUTF8 = '1'

    # Ensure base python is available
    $basePython = $null
    if ($env:GIS_PYTHON) {
        if (-not (Test-Python $env:GIS_PYTHON)) { throw 'GIS_PYTHON must point to a working 64-bit Python 3.11-3.13 executable.' }
        $basePython = $env:GIS_PYTHON
    } else {
        $systemPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
        if ($systemPython -and $systemPython.Source -notlike '*\WindowsApps\*' -and (Test-Python $systemPython.Source)) {
            $basePython = $systemPython.Source
        }

        # Python may be installed and registered with the Windows Python Launcher
        # without adding python.exe to PATH. Reuse it before attempting a download.
        if (-not $basePython) {
            $pythonLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
            if ($pythonLauncher) {
                foreach ($version in @('3.13', '3.12', '3.11')) {
                    try {
                        $candidate = (& $pythonLauncher.Source "-$version" -c 'import sys; print(sys.executable)' 2>$null | Out-String).Trim()
                        if ($candidate -and (Test-Python $candidate)) {
                            $basePython = $candidate
                            Write-Host "[INFO] Using Python $version from Windows Launcher: $basePython"
                            break
                        }
                    } catch {}
                }
            }
        }
    }

    if (-not $basePython) {
        # Check managed python first
        $managed = (& $uvExe python find --managed-python 3.13 2>$null | Out-String).Trim()
        if ($managed -and (Test-Python $managed)) {
            $basePython = $managed
        }
    }

    if (-not $basePython) {
        Write-Host '[DOWNLOAD] Python is missing or unsupported. Downloading local Python 3.13...'
        $pySuccess = $false
        try {
            & $uvExe python install 3.13 --no-bin
            if ($LASTEXITCODE -eq 0) { $pySuccess = $true }
        } catch {}
        if (-not $pySuccess) {
            Write-Host ''
            Write-Host '[ERROR] 自动下载 Python 3.13 失败。' -ForegroundColor Red
            Write-Host '说明：uv 下载 Python 依赖 GitHub Releases，国内直连通常不可达。' -ForegroundColor Yellow
            Write-Host '注意：国内 PyPI 镜像源仅能加速第三方 Python 依赖包，无法用于下载 Python 解释器本身！' -ForegroundColor Yellow
            Write-Host ''
            Write-Host '【解决办法（任选其一）】:' -ForegroundColor Cyan
            Write-Host '  1. 从国内高速镜像站下载安装 64位 Python (推荐 3.13 / 3.12 / 3.11):'
            Write-Host '     - 华为云镜像 (推荐): https://mirrors.huaweicloud.com/python/3.13.0/python-3.13.0-amd64.exe'
            Write-Host '     - 淘宝/npm 镜像: https://registry.npmmirror.com/-/binary/python/3.13.0/python-3.13.0-amd64.exe'
            Write-Host '     ★ 安装时务必勾选底部的【Add python.exe to PATH】！安装后重新运行 start.bat。' -ForegroundColor Green
            Write-Host '  2. 若已在自定义路径安装了 Python 3.11-3.13，可在启动前指定环境变量:'
            Write-Host '     set GIS_PYTHON=C:\你的Python路径\python.exe'
            Write-Host '     start.bat'
            Write-Host ''
            throw 'Python 3.11-3.13 is missing and cannot be downloaded from GitHub. Please install Python manually.'
        }
        $basePython = (& $uvExe python find --managed-python 3.13 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not (Test-Python $basePython)) { throw 'Downloaded Python could not be started.' }
    }

    if (-not (Test-Path -LiteralPath $runtimePython)) {
        if (Test-Path -LiteralPath $venvDir) {
            Backup-And-Reset-Venv 'Creating fresh virtual environment...'
        }
        & $uvExe venv --python $basePython $venvDir
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
    }

    Write-Host '[2/3] Installing missing dependencies. The first run may take several minutes...'
    $requirements = Join-Path $projectRoot 'backend\requirements.txt'
    & $uvExe pip install --python $runtimePython -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[RETRY] Default package source failed. Trying the Tsinghua mirror...'
        & $uvExe pip install --python $runtimePython -r $requirements --index-url 'https://pypi.tuna.tsinghua.edu.cn/simple'
        if ($LASTEXITCODE -ne 0) {
            if (Test-Path -LiteralPath $venvDir) {
                Backup-And-Reset-Venv 'Dependency installation failed on existing .venv. Rebuilding a clean environment...'
                & $uvExe venv --python $basePython $venvDir
                & $uvExe pip install --python $runtimePython -r $requirements --index-url 'https://pypi.tuna.tsinghua.edu.cn/simple'
            }
            if ($LASTEXITCODE -ne 0) { throw 'Both dependency sources failed. Check the network/proxy and run start.bat again.' }
        }
    }

    Write-Host '[3/3] Verifying the installed environment...'
    & $uvExe pip check --python $runtimePython
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependency versions are inconsistent.' }
    & $runtimePython $checker
    if ($LASTEXITCODE -ne 0) { throw 'Runtime verification failed. See the missing package or import error above.' }
    Save-Runtime
    Write-Host '[READY] Installation completed. Starting GIS-WORKTABLE...'
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'First-time setup needs Internet access and a writable project folder.'
    Write-Host 'Keep this window open to read the error. Retry by double-clicking start.bat.'
    exit 1
} finally {
    if ($lockStream) {
        $lockStream.Close()
        $lockStream.Dispose()
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}
