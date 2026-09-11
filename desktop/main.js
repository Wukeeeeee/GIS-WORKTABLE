/**
 * GIS-WORKTABLE 本地客户端外壳
 *
 * 职责：
 *  1. 检测后端（127.0.0.1:8000）是否已运行
 *  2. 未运行时，用本地 Python 启动 uvicorn（工作目录 = 项目根）
 *  3. 等待健康检查通过后，创建 Electron 窗口加载前端
 *  4. 窗口关闭时，仅结束"本客户端拉起的"后端进程（外部已有后端不动）
 *
 * 用法：
 *  npm start                 # 正常启动
 *  npm run start:dev         # 开发模式（保留 --dev 传给后端）
 */

const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

const PROJECT_ROOT = path.join(__dirname, '..');
const BACKEND_URL = 'http://127.0.0.1:8000';
const HEALTH_URL = `${BACKEND_URL}/api/health`;
const PORT = 8000;
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
    'D:\\python\\python.exe',
    'python',
    'python3',
  ].filter(Boolean);
  for (const py of candidates) {
    try {
      require('child_process').execSync(`"${py}" --version`, { stdio: 'ignore', timeout: 5000 });
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
      const resp = await fetch(HEALTH_URL, { signal: ctrl.signal });
      clearTimeout(timer);
      if (resp.ok) return true;
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
  // 1) 端口已被占用 → 直接认为后端可用（可能是外部服务）
  if (await isPortInUse(PORT)) {
    console.log('[GIS-Desktop] 端口 8000 已被占用，尝试健康检查...');
    if (await waitForBackend(10000)) {
      console.log('[GIS-Desktop] 复用已运行的后端');
      backendSpawned = false;
      return true;
    }
    console.warn('[GIS-Desktop] 端口被占用但健康检查失败，可能不是本项目的后端');
  }

  // 2) 尝试探测健康检查（后端已在运行但端口检查异常的情况）
  if (await waitForBackend(5000)) {
    console.log('[GIS-Desktop] 检测到后端已运行');
    backendSpawned = false;
    return true;
  }

  // 3) 启动后端
  const python = findPython();
  if (!python) {
    dialog.showErrorBox(
      '未找到 Python',
      '无法定位 Python 解释器。\n\n请通过环境变量 GIS_PYTHON 指定 Python 路径，例如：\nset GIS_PYTHON=D:\\python\\python.exe'
    );
    return false;
  }

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
