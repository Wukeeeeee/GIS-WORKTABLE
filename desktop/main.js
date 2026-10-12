/**
 * GIS-WORKTABLE 本地客户端外壳
 *
 * 职责：
 *  1. 使用 GIS_PORT 或默认 8000 端口，只复用当前仓库的后端
 *  2. 未运行时，用本地 Python 启动 uvicorn（工作目录 = 项目根）
 *  3. 等待健康检查通过后，创建 Electron 窗口加载前端
 *  4. 窗口关闭时，仅结束"本客户端拉起的"后端进程（外部已有后端不动）
 *
 * 用法：
 *  npm start                 # 正常启动
 *  npm run start:dev         # 开发模式（保留 --dev 传给后端）
 */

const { app, BrowserWindow, dialog } = require('electron');
const { spawn, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

const PROJECT_ROOT = path.join(__dirname, '..');
let PORT;
let BACKEND_URL;
let HEALTH_URL;
const LOG_DIR = path.join(__dirname, 'logs');

let backendProc = null;      // 本客户端拉起的后端进程
let backendSpawned = false;  // 标记后端是否由本客户端拉起
let windowMain = null;

// ============================================================
// 后端进程管理
// ============================================================

/** 探测可用的 Python 解释器 */
function findPython() {
  const candidates = [
    process.env.GIS_PYTHON,
    path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, '.venv', 'bin', 'python'),
    'python',
    'python3',
  ].filter(Boolean);
  for (const py of candidates) {
    try {
      execFileSync(py, ['--version'], { stdio: 'ignore', timeout: 5000, windowsHide: true });
      return py;
    } catch {
      // 继续尝试下一个
    }
  }
  return null;
}

/** 检查指定端口是否已被监听 */
function isPortInUse(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(true));
    srv.once('listening', () => {
      srv.close(() => resolve(false));
    });
    srv.listen(port, '127.0.0.1');
  });
}

/** 探测后端健康检查，timeout 毫秒内返回 true/false */
async function waitForBackend(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 3000);
      try {
        const resp = await fetch(HEALTH_URL, { signal: ctrl.signal });
        if (resp.ok) {
          const data = await resp.json();
          const normalize = (p) => process.platform === 'win32' ? path.resolve(p).toLowerCase() : path.resolve(p);
          if (data.status === 'ok' && data.service === 'gis-worktable'
              && typeof data.workspace === 'string'
              && normalize(data.workspace) === normalize(fs.realpathSync(PROJECT_ROOT))) return true;
        }
      } finally {
        clearTimeout(timer);
      }
    } catch {
      // 后端还没起来，继续轮询
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

/** 启动后端（uvicorn），日志写入 desktop/logs/backend.log */
function startBackend(python) {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  const logFd = fs.openSync(path.join(LOG_DIR, 'backend.log'), 'a');

  const args = ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(PORT)];
  if (process.argv.includes('--dev')) args.push('--reload');

  console.log(`[GIS-Desktop] 启动后端: ${python} ${args.join(' ')} (cwd=${PROJECT_ROOT})`);
  backendProc = spawn(python, args, {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
    stdio: ['ignore', logFd, logFd],
    windowsHide: true,
  });

  backendProc.on('error', (err) => {
    console.error('[GIS-Desktop] 后端启动失败:', err);
  });
  backendProc.on('exit', (code, signal) => {
    console.log(`[GIS-Desktop] 后端进程退出 code=${code} signal=${signal}`);
    if (windowMain && !windowMain.isDestroyed()) {
      // 后端意外退出，告知用户
      dialog.showErrorBox(
        'GIS-WORKTABLE 后端已停止',
        `后端进程意外退出（code=${code} signal=${signal}）。\n\n请查看日志：${path.join(LOG_DIR, 'backend.log')}\n\n客户端将关闭。`
      );
      app.quit();
    }
  });
  return backendProc;
}

// ============================================================
// 主流程
// ============================================================

async function ensureBackend() {
  const python = findPython();
  if (!python) {
    dialog.showErrorBox('未找到 Python', '请安装 Python，或通过 GIS_PYTHON 指定解释器路径。');
    return false;
  }
  try {
    PORT = Number(execFileSync(python, ['-m', 'backend.launcher', 'select'], {
      cwd: PROJECT_ROOT, encoding: 'utf8', timeout: 20000, windowsHide: true,
    }).trim());
    if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) throw new Error('Invalid backend port');
    BACKEND_URL = `http://127.0.0.1:${PORT}`;
    HEALTH_URL = `${BACKEND_URL}/api/health`;
  } catch (err) {
    const detail = String(err.stderr || err.message || err);
    const conflict = detail.match(/Port (\d+) is occupied by another service or checkout/);
    dialog.showErrorBox('无法启动 GIS 工作台', conflict
      ? `端口 ${conflict[1]} 已被其他项目或另一份仓库占用。\n\n请先关闭占用该端口的服务，再重新启动。工作台默认使用 8000。\n\n如需使用其他端口，请明确设置 GIS_PORT。`
      : `无法检查后端端口，请确认 Python 和 GIS_PORT 配置。\n\n${detail.trim().split('\n').pop()}`);
    return false;
  }
  // 仅复用同一仓库、身份匹配的 GIS 服务。
  if (await isPortInUse(PORT)) {
    console.log(`[GIS-Desktop] 端口 ${PORT} 已被占用，检查项目身份...`);
    if (await waitForBackend(10000)) {
      console.log('[GIS-Desktop] 复用已运行的后端');
      backendSpawned = false;
      return true;
    }
    dialog.showErrorBox('端口冲突', `端口 ${PORT} 的服务身份不匹配，请重新启动或设置 GIS_PORT。`);
    return false;
  }

  // 3) 启动后端
  startBackend(python);
  backendSpawned = true;

  try {
    if (!(await waitForBackend())) {
      dialog.showErrorBox(
        '后端启动超时',
        `90 秒内后端未就绪。\n\n请查看日志：${path.join(LOG_DIR, 'backend.log')}`
      );
      return false;
    }
  } catch (err) {
    console.error('[GIS-Desktop] 等待后端出错:', err);
    dialog.showErrorBox('后端启动异常', `等待后端就绪时发生异常：${err.message}`);
    return false;
  }
  console.log('[GIS-Desktop] 后端就绪');
  return true;
}

function createWindow() {
  windowMain = new BrowserWindow({
    title: 'GIS-WORKTABLE - AI 智能 GIS 工作平台',
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#1a1d26',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  windowMain.loadURL(BACKEND_URL);

  // 诊断：记录渲染进程异常，避免窗口"静默消失"
  windowMain.webContents.on('render-process-gone', (e, details) => {
    console.error(`[GIS-Desktop] 渲染进程异常退出: reason=${details.reason} exitCode=${details.exitCode}`);
  });
  windowMain.webContents.on('did-fail-load', (e, code, desc, url) => {
    console.error(`[GIS-Desktop] 页面加载失败: code=${code} desc=${desc} url=${url}`);
  });
  windowMain.webContents.on('console-message', (e, level, message, line, sourceId) => {
    if (level >= 2) console.log(`[GIS-Desktop][渲染] ${message} (${sourceId}:${line})`);
  });

  windowMain.on('ready-to-show', () => {
    windowMain.show();
    windowMain.focus();
    windowMain.webContents.focus();
  });

  // 点击窗口时强制把键盘焦点交给页面，避免"点击了输入框但打不了字"
  windowMain.on('focus', () => {
    if (windowMain && !windowMain.isDestroyed()) windowMain.webContents.focus();
  });

  windowMain.on('closed', () => {
    windowMain = null;
    shutdownBackend();
  });
}

/** 只结束本客户端拉起的后端；外部已有后端保持不动 */
function shutdownBackend() {
  if (backendSpawned && backendProc && !backendProc.killed) {
    console.log('[GIS-Desktop] 关闭由本客户端启动的后端进程');
    try {
      backendProc.kill();
    } catch (err) {
      console.error('[GIS-Desktop] 结束后端进程失败:', err);
    }
  }
}

// ============================================================
// Electron 生命周期
// ============================================================

app.whenReady().then(async () => {
  const ok = await ensureBackend();
  if (!ok) {
    app.quit();
    return;
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  // 所有平台关闭窗口即退出（客户端模式）
  app.quit();
});

app.on('before-quit', () => {
  shutdownBackend();
});
