const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter, once } = require('node:events');
const childProcess = require('node:child_process');
const { randomUUID } = require('node:crypto');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'desktop/main.js'), 'utf8');

async function bounded(promise) {
  let timer;
  try {
    return await Promise.race([promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('helper timeout')), 3000); })]);
  } finally { clearTimeout(timer); }
}

function boot(options = {}) {
  const calls = { exec: [], spawn: [], treeKill: [], closeFd: [], errors: [], unlink: [], endpoints: [] };
  let now = 0;
  let ipcAttempts = 0;
  let windows = [];
  const proc = new EventEmitter();
  Object.assign(proc, { pid: 12345, exitCode: null, signalCode: null, killed: false,
    kill() { this.killed = true; calls.directKill = (calls.directKill || 0) + 1; } });
  const app = new EventEmitter();
  app.getPath = (name) => path.join(root, '.codex-test-tmp', name);
  app.whenReady = () => options.startApp ? Promise.resolve() : new Promise(() => {});
  app.quit = () => { calls.quit = (calls.quit || 0) + 1; app.emit('before-quit'); };
  class Window extends EventEmitter {
    constructor() {
      super();
      windows.push(this);
      this.webContents = Object.assign(new EventEmitter(), { focus() {} });
    }
    isDestroyed() { return false; }
    isMinimized() { return true; }
    restore() { calls.restore = (calls.restore || 0) + 1; }
    show() { calls.show = (calls.show || 0) + 1; }
    focus() { calls.focus = (calls.focus || 0) + 1; }
    loadURL(url) {
      calls.url = url;
      return options.loadError ? Promise.reject(new Error('page failed')) : Promise.resolve();
    }
    static getAllWindows() { return windows; }
  }
  const fakeFs = {
    realpathSync: () => options.workspace || root,
    existsSync: () => false,
    mkdirSync() {},
    readFileSync() { if (options.savedPython) return options.savedPython; throw new Error('missing'); },
    openSync() { if (options.logError) throw new Error('log denied'); return 12; },
    closeSync(fd) { calls.closeFd.push(fd); },
    unlinkSync(file) { calls.unlink.push(file); },
  };
  const fakeNet = {
    createServer(onConnection) {
      const server = new EventEmitter();
      server.close = (cb) => { if (cb) cb(); };
      server.listen = (target, cb) => {
        queueMicrotask(() => {
          if (typeof target === 'number') {
            if (options.portInUse) server.emit('error', Object.assign(new Error('in use'), { code: 'EADDRINUSE' }));
            else server.emit('listening');
          } else {
            calls.endpoints.push(target);
            calls.onConnection = onConnection;
            ipcAttempts += 1;
            if (options.ipcConflict && (!options.staleSocket || ipcAttempts === 1)) {
              server.emit('error', Object.assign(new Error('in use'), { code: 'EADDRINUSE' }));
            } else cb();
          }
        });
      };
      return server;
    },
    createConnection() {
      const socket = new EventEmitter();
      socket.setTimeout = () => socket;
      socket.end = () => {};
      queueMicrotask(() => options.connectError
        ? socket.emit('error', Object.assign(new Error('refused'), { code: options.connectError }))
        : socket.emit('connect'));
      return socket;
    },
  };
  const fakeChildProcess = {
    execFile(py, args, opts, callback) {
      calls.exec.push({ py, args, opts });
      queueMicrotask(() => callback(options.runtimeReady && !options.runtimeReady(py)
        ? new Error('runtime not ready') : null, '', ''));
    },
    spawn(py, args, opts) {
      calls.spawn.push({ py, args, opts });
      if (options.spawnThrows) throw new Error('spawn denied');
      if (options.realSpawn) return options.realSpawn(py, args, opts);
      if (options.spawnError) {
        proc.pid = undefined;
        queueMicrotask(() => proc.emit('error', new Error('spawn failed')));
      }
      return proc;
    },
    execFileSync(file, args, opts) {
      calls.treeKill.push({ file, args, opts });
      if (options.realTreeKill) return childProcess.execFileSync(file, args, opts);
      if (options.killFails) throw new Error('taskkill failed');
    },
  };
  const processStub = {
    platform: options.platform || process.platform, env: options.env || {},
    argv: options.dev ? ['electron', '.', '--dev'] : [],
    kill(pid, signal) { calls.groupKill = { pid, signal }; },
  };
  const modules = {
    electron: { app, BrowserWindow: Window, dialog: { showErrorBox(...args) { calls.errors.push(args); } } },
    child_process: fakeChildProcess, fs: fakeFs, net: options.realNet || fakeNet,
  };
  const context = vm.createContext({
    require(name) { return modules[name] || require(name); },
    __dirname: path.join(root, 'desktop'), process: processStub,
    console: { log() {}, error() {} }, AbortController,
    Date: class extends Date { static now() { return now; } },
    setTimeout(fn, ms) {
      const timer = { canceled: false };
      if (ms <= 1000) queueMicrotask(() => { if (!timer.canceled) { now += ms; fn(); } });
      return timer;
    },
    clearTimeout(timer) { timer.canceled = true; },
    async fetch() {
      calls.fetch = (calls.fetch || 0) + 1;
      return { ok: true, async json() {
        return options.health || { status: 'ok', service: 'gis-worktable', workspace: root,
          profile: options.env?.GISWTB_PROFILE?.trim().toLowerCase() || 'default' };
      } };
    },
  });
  vm.runInContext(source, context, { filename: path.join(root, 'desktop/main.js') });
  return { calls, proc, app, context, now: () => now,
    run(code) { return vm.runInContext(code, context); } };
}

test('runtime selection skips incomplete environments and reuses the saved runtime', async () => {
  const h = boot({ savedPython: '\uFEFFD:/ready/python.exe\n',
    env: { GIS_PYTHON: 'D:/base/python.exe' }, runtimeReady: py => py === 'D:/ready/python.exe' });
  assert.equal(await h.run('findPython()'), 'D:/ready/python.exe');
  assert.equal(h.calls.exec.length, 3);
  assert.match(h.calls.exec[0].py, /\.venv/);
  assert.ok(h.calls.exec.every(call => call.args[0].endsWith('check_runtime.py')));
});

test('a ready project venv takes precedence over the base interpreter', async () => {
  const h = boot({ env: { GIS_PYTHON: 'D:/base/python.exe' } });
  assert.match(await h.run('findPython()'), /\.venv/);
  assert.equal(h.calls.exec.length, 1);
});

test('reusing a matching backend does not require any Python interpreter', async () => {
  const h = boot({ portInUse: true, runtimeReady: () => false });
  assert.equal(await h.run('ensureBackend()'), true);
  assert.equal(h.calls.exec.length, 0);
  assert.equal(h.calls.spawn.length, 0);
  h.run('shutdownBackend()');
  assert.equal(h.calls.treeKill.length, 0);
});

test('a backend from another profile is never reused', async () => {
  const h = boot({ portInUse: true, health: { status: 'ok', service: 'gis-worktable',
    workspace: root, profile: 'other' } });
  assert.equal(await h.run('ensureBackend()'), false);
  assert.match(h.calls.errors[0][0], /端口冲突/);
  assert.equal(h.calls.spawn.length, 0);
  assert.equal(h.calls.exec.length, 0);
});

for (const port of ['8e3', '0', '65536', '-1', 'abc']) {
  test(`invalid port ${port} fails before any process is started`, async () => {
    const h = boot({ env: { GIS_PORT: port } });
    assert.equal(await h.run('ensureBackend()'), false);
    assert.equal(h.calls.spawn.length, 0);
    assert.equal(h.calls.exec.length, 0);
    assert.match(h.calls.errors[0][1], /GIS_PORT/);
  });
}

test('spawn failure is reported immediately and closes the parent log handle', async () => {
  const h = boot({ spawnError: true });
  assert.equal(await h.run('ensureBackend()'), false);
  assert.ok(h.now() < 90000);
  assert.deepEqual(h.calls.closeFd, [12]);
  assert.match(h.calls.errors[0][1], /spawn failed/);
  assert.equal(h.calls.treeKill.length, 0);
});

test('synchronous spawn errors also close the log handle', async () => {
  const h = boot({ spawnThrows: true });
  assert.equal(await h.run('ensureBackend()'), false);
  assert.deepEqual(h.calls.closeFd, [12]);
  assert.match(h.calls.errors[0][1], /spawn denied/);
});

test('log file errors reach the user instead of rejecting startup silently', async () => {
  const h = boot({ logError: true });
  assert.equal(await h.run('ensureBackend()'), false);
  assert.match(h.calls.errors[0][1], /log denied/);
  assert.equal(h.calls.spawn.length, 0);
});

test('startup timeout cleans up only the process tree it created', async () => {
  const h = boot({ platform: 'win32', health: { status: 'starting' } });
  assert.equal(await h.run('ensureBackend()'), false);
  assert.equal(h.calls.treeKill.length, 1);
  assert.deepEqual(Array.from(h.calls.treeKill[0].args), ['/PID', '12345', '/T', '/F']);
});

test('normal shutdown includes reload children and does not show a crash dialog', () => {
  const h = boot({ platform: 'win32', dev: true });
  h.run('PORT = 8000; startBackend("python"); createWindow(); shutdownBackend(); shutdownBackend();');
  h.proc.exitCode = 1;
  h.proc.emit('exit', 1, null);
  assert.equal(h.calls.treeKill.length, 1);
  assert.ok(h.calls.spawn[0].args.includes('--reload'));
  assert.equal(h.calls.errors.length, 0);
});

test('shutdown during a health request does not turn into a startup error', async () => {
  const h = boot({ platform: 'win32' });
  let complete;
  h.context.fetch = () => new Promise(resolve => { complete = resolve; });
  h.run('PORT = 8000; startBackend("python");');
  const waiting = h.run('waitForBackend()');
  h.run('shutdownBackend()');
  h.proc.exitCode = 0;
  complete({ ok: true, async json() { return {}; } });
  assert.equal(await waiting, false);
  assert.equal(h.calls.errors.length, 0);
});

test('canceled startup never displays a timeout dialog', async () => {
  const h = boot();
  h.run('waitForBackend = async () => { shuttingDown = true; return false; };');
  assert.equal(await h.run('ensureBackend()'), false);
  assert.equal(h.calls.errors.length, 0);
});

test('failed process termination is reported without an uncaught quit error', () => {
  const h = boot({ platform: 'win32', killFails: true });
  h.run('PORT = 8000; startBackend("python");');
  h.proc.kill = () => { throw new Error('access denied'); };
  assert.doesNotThrow(() => h.run('shutdownBackend()'));
  assert.match(h.calls.errors[0][0], /后端关闭失败/);
});

test('an exited child PID is never targeted again', () => {
  const h = boot({ platform: 'win32' });
  h.run('PORT = 8000; startBackend("python");');
  h.proc.exitCode = 1;
  h.run('shutdownBackend()');
  assert.equal(h.calls.treeKill.length, 0);
});

test('POSIX shutdown targets the isolated process group', () => {
  const h = boot({ platform: 'linux' });
  h.run('PORT = 8000; startBackend("python"); shutdownBackend();');
  assert.equal(h.calls.spawn[0].opts.detached, true);
  assert.deepEqual(h.calls.groupKill, { pid: -12345, signal: 'SIGTERM' });
});

test('page load failure is handled and closes the client', async () => {
  const h = boot({ loadError: true });
  h.run('createWindow()');
  await Promise.resolve();
  assert.match(h.calls.errors[0][0], /页面加载失败/);
  assert.equal(h.calls.quit, 1);
});

test('duplicate desktop startup signals the existing client and starts no backend', async () => {
  const h = boot({ ipcConflict: true });
  assert.equal(await h.run('claimDesktopInstance()'), false);
  assert.equal(h.calls.spawn.length, 0);
});

test('the instance key distinguishes workspaces, profiles, and ports', async () => {
  const setups = [boot(), boot({ workspace: path.join(root, 'other') }),
    boot({ env: { GIS_PORT: '8001' } }), boot({ env: { GISWTB_PROFILE: 'other' } })];
  for (const h of setups) assert.equal(await h.run('claimDesktopInstance()'), true);
  assert.equal(new Set(setups.map(h => h.calls.endpoints[0])).size, 4);
});

test('a duplicate launch restores and focuses the original window', async () => {
  const h = boot();
  assert.equal(await h.run('claimDesktopInstance()'), true);
  h.run('createWindow()');
  h.calls.onConnection({ end() {} });
  assert.equal(h.calls.restore, 1);
  assert.equal(h.calls.focus, 1);
});

test('an abandoned POSIX instance socket is recovered once', async () => {
  const h = boot({ platform: 'linux', ipcConflict: true, staleSocket: true, connectError: 'ECONNREFUSED' });
  assert.equal(await h.run('claimDesktopInstance()'), true);
  assert.deepEqual(h.calls.unlink, [h.calls.endpoints[0]]);
});

test('IPC permission errors do not remove another process socket', async () => {
  const h = boot({ platform: 'linux', ipcConflict: true, connectError: 'EACCES' });
  await assert.rejects(h.run('claimDesktopInstance()'), /refused/);
  assert.deepEqual(h.calls.unlink, []);
});

test('a failed instance setup is reported by the application startup handler', async () => {
  const h = boot({ startApp: true, ipcConflict: true, connectError: 'EACCES' });
  for (let i = 0; i < 20; i++) await Promise.resolve();
  assert.match(h.calls.errors[0][0], /客户端启动失败/);
  assert.equal(h.calls.quit, 1);
});

test('real Windows IPC allows one owner and signals the existing window',
  { skip: process.platform !== 'win32', timeout: 10000 }, async () => {
    const options = { realNet: require('node:net'), env: { GISWTB_PROFILE: `test-${randomUUID()}` } };
    const owner = boot(options);
    const second = boot(options);
    try {
      assert.equal(await owner.run('claimDesktopInstance()'), true);
      owner.run('createWindow()');
      assert.equal(await second.run('claimDesktopInstance()'), false);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(owner.calls.focus, 1);
    } finally {
      await new Promise(resolve => {
        owner.context.onClosed = resolve;
        owner.run('if (instanceServer) instanceServer.close(onClosed); else onClosed();');
      });
    }
  });

test('real Windows shutdown closes both an owned parent and its child',
  { skip: process.platform !== 'win32', timeout: 10000 }, async () => {
    const code = `const {spawn}=require('child_process');
      const child=spawn(process.execPath,['-e','setInterval(()=>process.stdout.write("beat\\\\n"),100)'],
        {stdio:['ignore',process.stdout,process.stderr],windowsHide:true});
      console.log('child-pid:'+child.pid); setInterval(()=>{},1000);`;
    let actualProc;
    let childPid;
    let treeClosed = false;
    const h = boot({ realTreeKill: true, realSpawn(py, args, opts) {
      actualProc = childProcess.spawn(process.execPath, ['-e', code], { ...opts, stdio: ['ignore', 'pipe', 'pipe'] });
      return actualProc;
    } });
    try {
      h.run('PORT = 8000; startBackend("python");');
      const closed = once(actualProc, 'close');
      const [chunk] = await bounded(once(actualProc.stdout, 'data'));
      childPid = Number(String(chunk).match(/child-pid:(\d+)/)?.[1]);
      assert.ok(childPid > 0);
      h.run('shutdownBackend();');
      // close 只有在所有继承 stdout 的子进程也退出后才会到达。
      await bounded(closed);
      treeClosed = true;
      assert.equal(h.calls.treeKill.length, 1);
    } finally {
      for (const pid of (treeClosed ? [] : [actualProc?.pid, childPid]).filter(Boolean)) {
        try { childProcess.execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'],
          { windowsHide: true, stdio: 'ignore', timeout: 3000 }); } catch { /* 已退出 */ }
      }
    }
  });

test('Windows desktop launcher preserves a failed npm start result',
  { skip: process.platform !== 'win32' }, () => {
    const base = path.join(root, '.codex-test-tmp');
    fs.mkdirSync(base, { recursive: true });
    const fixtureRoot = fs.mkdtempSync(path.join(base, 'desktop-launcher-'));
    try {
      const scripts = path.join(fixtureRoot, 'scripts');
      const desktop = path.join(fixtureRoot, 'desktop');
      const bin = path.join(fixtureRoot, 'bin');
      for (const folder of [scripts, desktop, bin]) fs.mkdirSync(folder);
      const script = path.join(scripts, 'start-desktop.bat');
      fs.copyFileSync(path.join(root, 'scripts/start-desktop.bat'), script);
      fs.writeFileSync(path.join(desktop, 'package.json'), '{}');
      fs.writeFileSync(path.join(bin, 'npm.cmd'), '@echo off\r\necho fake-npm-failure\r\nexit /b 7\r\n');
      const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toUpperCase() !== 'PATH'));
      env.PATH = `${bin};${process.env.PATH}`;
      const result = childProcess.spawnSync(process.env.ComSpec || 'cmd.exe', ['/d', '/c', script], {
        cwd: fixtureRoot, env, windowsHide: true, timeout: 3000, encoding: 'utf8',
      });
      assert.equal(result.error, undefined);
      assert.equal(result.status, 7, result.stdout + result.stderr);
    } finally {
      const target = fs.realpathSync(fixtureRoot);
      assert.ok(target.startsWith(fs.realpathSync(base) + path.sep));
      fs.rmSync(target, { recursive: true, force: true });
    }
  });
