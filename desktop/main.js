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
 *  npm run start:dev         # 开发模式（后端启用 --reload）
 */

const { app, BrowserWindow, dialog } = require('electron');
const { spawn, execFile, execFileSync } = require('child_process');
const { promisify } = require('util');
const { createHash } = require('crypto');
const path = require('path');
const fs = require('fs');
const net = require('net');

const PROJECT_ROOT = path.join(__dirname, '..');
let PORT;
let BACKEND_URL;
let HEALTH_URL;
const LOG_DIR = path.join(__dirname, 'logs');
const execFileAsync = promisify(execFile);
const PROFILE = (process.env.GISWTB_PROFILE || 'default').trim().toLowerCase() || 'default';

let backendProc = null;      // 本客户端拉起的后端进程
let backendSpawned = false;  // 标记后端是否由本客户端拉起
let windowMain = null;
let backendStartError = null;
let shuttingDown = false;
let instanceServer = null;

// ============================================================
// 后端进程管理
// ============================================================

/** 探测可用的 Python 解释器 */
async function findPython() {
  let savedPython = '';
  try {
    savedPython = fs.readFileSync(path.join(PROJECT_ROOT, '.bootstrap', 'python-path.txt'), 'utf8')
      .replace(/^\uFEFF/, '').trim();
  } catch { /* 尚未运行环境安装器 */ }
  const candidates = [
    path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(PROJECT_ROOT, '.venv', 'bin', 'python'),
    savedPython,
    process.env.GIS_PYTHON,
    'python',
    'python3',
  ].filter(Boolean);
  for (const py of new Set(candidates)) {
    try {
      await execFileAsync(py, [path.join(PROJECT_ROOT, 'scripts', 'check_runtime.py')], {
        cwd: PROJECT_ROOT, timeout: 30000, windowsHide: true,
      });
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

function assertBackendAlive() {
  if (backendSpawned && (backendStartError || backendProc.exitCode !== null || backendProc.signalCode !== null)) {
    throw backendStartError || new Error(`后端进程提前退出（code=${backendProc.exitCode} signal=${backendProc.signalCode}）`);
  }
}

/** 在等待预算内检查服务身份；本客户端启动的进程退出时立即失败。 */
async function waitForBackend(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (shuttingDown) return false;
    assertBackendAlive();
    let ready = false;
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), Math.min(3000, timeoutMs - (Date.now() - start)));
      try {
        const resp = await fetch(HEALTH_URL, { signal: ctrl.signal });
        if (resp.ok) {
          const data = await resp.json();
          const normalize = (p) => process.platform === 'win32' ? path.resolve(p).toLowerCase() : path.resolve(p);
          ready = !!(data && data.status === 'ok' && data.service === 'gis-worktable' && data.profile === PROFILE
              && typeof data.workspace === 'string'
              && normalize(data.workspace) === normalize(fs.realpathSync(PROJECT_ROOT)));
        }
      } finally {
        clearTimeout(timer);
      }
    } catch {
      // 后端还没起来，继续轮询
    }
    if (shuttingDown) return false;
    assertBackendAlive();
    if (ready) return true;
    const remaining = timeoutMs - (Date.now() - start);
    if (remaining > 0) await new Promise((r) => setTimeout(r, Math.min(1000, remaining)));
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
  backendStartError = null;
  try {
    backendProc = spawn(python, args, {
      cwd: PROJECT_ROOT,
      env: { ...process.env },
      stdio: ['ignore', logFd, logFd],
      windowsHide: true,
      detached: process.platform !== 'win32',
    });
    backendSpawned = true;
  } finally {
    fs.closeSync(logFd);
  }

  backendProc.on('error', (err) => {
    backendStartError = err;
    console.error('[GIS-Desktop] 后端启动失败:', err);
  });
  backendProc.on('exit', (code, signal) => {
    console.log(`[GIS-Desktop] 后端进程退出 code=${code} signal=${signal}`);
    if (!shuttingDown && windowMain && !windowMain.isDestroyed()) {
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

/** 同一仓库、端口和配置只保留一个客户端；重复启动时聚焦现有窗口。 */
async function claimDesktopInstance(retryStaleSocket = true) {
  const workspace = fs.realpathSync(PROJECT_ROOT);
  const key = createHash('sha256').update(JSON.stringify([
    process.platform === 'win32' ? workspace.toLowerCase() : workspace,
    Number(process.env.GIS_PORT || 8000), PROFILE, app.getPath('userData'),
  ])).digest('hex').slice(0, 24);
  const endpoint = process.platform === 'win32'
    ? `\\\\.\\pipe\\gis-worktable-${key}`
    : path.join(app.getPath('temp'), `gis-worktable-${key}.sock`);
  const server = net.createServer((socket) => {
    socket.end();
    if (windowMain && !windowMain.isDestroyed()) {
      if (windowMain.isMinimized()) windowMain.restore();
      windowMain.show();
      windowMain.focus();
    }
  });
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(endpoint, resolve);
    });
    instanceServer = server;
    return true;
  } catch (err) {
    if (err.code !== 'EADDRINUSE') throw err;
  }
  try {
    await new Promise((resolve, reject) => {
      const client = net.createConnection(endpoint);
      client.setTimeout(1000, () => client.destroy(new Error('现有客户端未响应')));
      client.once('error', reject);
      client.once('connect', () => { client.end(); resolve(); });
    });
    return false;
  } catch (err) {
    if (retryStaleSocket && process.platform !== 'win32' && err.code === 'ECONNREFUSED') {
      fs.unlinkSync(endpoint);
      return claimDesktopInstance(false);
    }
    throw err;
  }
}

async function ensureBackend() {
  try {
    const configured = (process.env.GIS_PORT || '8000').trim();
    PORT = Number(configured);
    if (!/^\+?\d+$/.test(configured) || !Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
      throw new Error('GIS_PORT 必须是 1–65535 之间的整数');
    }
    BACKEND_URL = `http://127.0.0.1:${PORT}`;
    HEALTH_URL = `${BACKEND_URL}/api/health`;
  } catch (err) {
    dialog.showErrorBox('无法启动 GIS 工作台', err.message);
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
    dialog.showErrorBox('端口冲突', `端口 ${PORT} 已被占用，服务身份不匹配或尚未就绪。请先关闭占用服务，或明确设置 GIS_PORT。`);
    return false;
  }

  try {
    const python = await findPython();
    if (!python) {
      dialog.showErrorBox('Python 环境未就绪', '请先运行 start.bat 完成环境安装，或通过 GIS_PYTHON 指定已安装项目依赖的解释器。');
      return false;
    }
    if (shuttingDown) return false;
    startBackend(python);
    if (!(await waitForBackend())) {
      if (shuttingDown) return false;
      dialog.showErrorBox(
        '后端启动超时',
        `90 秒内后端未就绪。\n\n请查看日志：${path.join(LOG_DIR, 'backend.log')}`
      );
      shutdownBackend();
      return false;
    }
  } catch (err) {
    if (shuttingDown) return false;
    console.error('[GIS-Desktop] 等待后端出错:', err);
    dialog.showErrorBox('后端启动异常', `等待后端就绪时发生异常：${err.message}`);
    shutdownBackend();
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

  windowMain.loadURL(BACKEND_URL).catch((err) => {
    if (shuttingDown) return;
    dialog.showErrorBox('工作台页面加载失败', `无法加载工作台：${err.message}\n\n请查看日志：${path.join(LOG_DIR, 'backend.log')}`);
    app.quit();
  });

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
  shuttingDown = true;
  if (backendSpawned && backendProc && backendProc.pid
      && backendProc.exitCode === null && backendProc.signalCode === null) {
    console.log('[GIS-Desktop] 关闭由本客户端启动的后端进程');
    backendSpawned = false;
    try {
      if (process.platform === 'win32') {
        execFileSync('taskkill', ['/PID', String(backendProc.pid), '/T', '/F'], {
          windowsHide: true, stdio: 'ignore', timeout: 5000,
        });
      } else {
        process.kill(-backendProc.pid, 'SIGTERM');
      }
    } catch (err) {
      console.error('[GIS-Desktop] 结束后端进程失败:', err);
      try {
        if (backendProc.exitCode === null && backendProc.signalCode === null) backendProc.kill();
      } catch (fallbackError) {
        console.error('[GIS-Desktop] 后端主进程也未能停止:', fallbackError);
        dialog.showErrorBox('后端关闭失败', `无法停止后端，请运行 stop.bat 或手动关闭本次启动的进程（PID ${backendProc.pid}）。`);
      }
    }
  }
}

// ============================================================
// Electron 生命周期
// ============================================================

app.whenReady().then(async () => {
  if (!(await claimDesktopInstance())) {
    app.quit();
    return;
  }
  const ok = await ensureBackend();
  if (!ok || shuttingDown) {
    app.quit();
    return;
  }
  createWindow();

  app.on('activate', () => {
    if (!shuttingDown && BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}).catch((err) => {
  dialog.showErrorBox('客户端启动失败', err.message || String(err));
  app.quit();
});

app.on('window-all-closed', () => {
  // 所有平台关闭窗口即退出（客户端模式）
  app.quit();
});

app.on('before-quit', () => {
  if (instanceServer) {
    const server = instanceServer;
    instanceServer = null;
    server.close();
  }
  shutdownBackend();
});
