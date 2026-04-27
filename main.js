/**
 * Lucy OS v5 — Electron Main Process
 * ====================================
 * Launch flow:
 *   1. Start lucy-server (Node.js Express backend, port 3001)
 *   2. Start Python bridge service (port 8765)
 *   3. Load React app — from dist/index.html if built, else Vite dev server
 *
 * Double-click LucyOS.exe  OR  run START.bat → option 1
 */

const { app, BrowserWindow, ipcMain, dialog, Tray, Menu, nativeImage } = require('electron');
const path   = require('path');
const fs     = require('fs');
const { spawn, execSync, spawnSync } = require('child_process');

// ── Config ──────────────────────────────────────────────────────────────────
const BRIDGE_PORT    = 8765;
const TERMINAL_PORT  = 8766;
const LUCY_PORT      = 3001;   // lucy-server Express backend
const VITE_PORT      = 5173;

const BRIDGE_SCRIPT   = path.join(__dirname, '..', 'lucy-bridge', 'lucy_bridge_service.py');
const TERMINAL_SCRIPT = path.join(__dirname, '..', 'lucy-terminal-server.py');
const LUCY_SERVER_DIR = path.join(__dirname, '..', 'lucy-server');
const LUCY_SERVER_JS  = path.join(LUCY_SERVER_DIR, 'server.mjs');
const DIST_INDEX      = path.join(__dirname, '..', 'dist', 'index.html');

// IS_DEV = only true when explicitly running via `npm run dev` (NODE_ENV=development)
// When user runs START.bat option [1], NODE_ENV is NOT set → we load dist/index.html
const IS_DEV_EXPLICIT = process.env.NODE_ENV === 'development';
const IS_WIN          = process.platform === 'win32';

let mainWindow   = null;
let tray         = null;
let bridgeProc   = null;
let terminalProc = null;
let lucyProc     = null;
let bridgeReady  = false;
let lucyReady    = false;

// ════════════════════════════════════════════════════════════════════════════
// Determine how to load the app
// ════════════════════════════════════════════════════════════════════════════
function getLoadMode() {
  if (IS_DEV_EXPLICIT) {
    // Explicit dev mode — use Vite dev server
    return { mode: 'vite', url: `http://localhost:${VITE_PORT}` };
  }
  if (fs.existsSync(DIST_INDEX)) {
    // Built files exist — load them directly (works offline, no Vite needed)
    return { mode: 'file', file: DIST_INDEX };
  }
  // No dist/ and not in dev mode — show a helpful error page
  return { mode: 'error', message: 'Run START.bat and choose option [4] Dev Mode, or [1] to build first.' };
}

// ════════════════════════════════════════════════════════════════════════════
// Find Python executable
// ════════════════════════════════════════════════════════════════════════════
function findPython() {
  if (app.isPackaged) {
    const bundled = path.join(process.resourcesPath, 'python', 'python.exe');
    if (fs.existsSync(bundled)) return bundled;
    const bundledLinux = path.join(process.resourcesPath, 'python', 'python3');
    if (fs.existsSync(bundledLinux)) return bundledLinux;
  }

  const candidates = IS_WIN ? ['python', 'python3', 'py'] : ['python3', 'python'];
  for (const cmd of candidates) {
    try {
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      return cmd;
    } catch {}
  }
  return null;
}

// ════════════════════════════════════════════════════════════════════════════
// Start lucy-server (Node.js Express backend — port 3001)
// ════════════════════════════════════════════════════════════════════════════
function startLucyServer() {
  return new Promise((resolve) => {
    if (!fs.existsSync(LUCY_SERVER_JS)) {
      console.warn('[electron] lucy-server/server.mjs not found — skipping');
      resolve(false);
      return;
    }

    console.log('[electron] Starting lucy-server on port', LUCY_PORT);

    // Install deps if node_modules missing
    const modsPath = path.join(LUCY_SERVER_DIR, 'node_modules');
    if (!fs.existsSync(modsPath)) {
      console.log('[electron] Installing lucy-server dependencies...');
      try {
        spawnSync('npm', ['install', '--prefer-offline'], {
          cwd: LUCY_SERVER_DIR,
          stdio: 'ignore',
          shell: IS_WIN,
        });
      } catch (e) {
        console.warn('[electron] npm install for lucy-server failed:', e.message);
      }
    }

    lucyProc = spawn('node', [LUCY_SERVER_JS], {
      cwd: LUCY_SERVER_DIR,
      env: { ...process.env, PORT: String(LUCY_PORT) },
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: IS_WIN,
      detached: false,
    });

    lucyProc.stdout.on('data', d => {
      const msg = d.toString().trim();
      console.log('[lucy-server]', msg);
      if (msg.includes('listening') || msg.includes('started') || msg.includes(String(LUCY_PORT))) {
        lucyReady = true;
        resolve(true);
      }
    });

    lucyProc.stderr.on('data', d => console.error('[lucy-server]', d.toString().trim()));
    lucyProc.on('error', err => { console.error('[lucy-server] Failed:', err.message); resolve(false); });
    lucyProc.on('exit', code => { lucyReady = false; console.log('[lucy-server] Exited:', code); });

    // Resolve after 5s regardless
    setTimeout(() => { if (!lucyReady) { lucyReady = true; resolve(true); } }, 5000);
  });
}

// ════════════════════════════════════════════════════════════════════════════
// Start Python bridge service (port 8765)
// ════════════════════════════════════════════════════════════════════════════
function startBridge() {
  return new Promise((resolve) => {
    const python = findPython();
    if (!python) {
      console.warn('[electron] Python not found — bridge will be offline');
      resolve(false);
      return;
    }
    if (!fs.existsSync(BRIDGE_SCRIPT)) {
      console.warn('[electron] Bridge script not found:', BRIDGE_SCRIPT);
      resolve(false);
      return;
    }

    console.log('[electron] Starting bridge on port', BRIDGE_PORT);

    // Silent pip install
    const pipInstall = spawn(python, ['-m', 'pip', 'install', '--quiet',
      'fastapi', 'uvicorn[standard]', 'pydantic', 'websockets'], { stdio: 'ignore', shell: IS_WIN });

    pipInstall.on('close', () => {
      bridgeProc = spawn(python, [BRIDGE_SCRIPT, '--mode', 'auto', '--port', String(BRIDGE_PORT)], {
        stdio: ['ignore', 'pipe', 'pipe'],
        shell: IS_WIN,
        detached: false,
      });

      bridgeProc.stdout.on('data', d => {
        const msg = d.toString().trim();
        console.log('[bridge]', msg);
        if (msg.includes('Uvicorn running') || msg.includes('Application startup complete')) {
          bridgeReady = true;
          resolve(true);
        }
      });
      bridgeProc.stderr.on('data', d => console.error('[bridge]', d.toString().trim()));
      bridgeProc.on('error', err => { console.error('[bridge] Failed:', err.message); resolve(false); });
      bridgeProc.on('exit', code => { bridgeReady = false; });

      setTimeout(() => { if (!bridgeReady) { bridgeReady = true; resolve(false); } }, 10000);
    });
  });
}

// ════════════════════════════════════════════════════════════════════════════
// Start terminal server (port 8766) — optional, no-op if not found
// ════════════════════════════════════════════════════════════════════════════
function startTerminal() {
  const python = findPython();
  if (!python || !fs.existsSync(TERMINAL_SCRIPT)) return;

  console.log('[electron] Starting terminal server on port', TERMINAL_PORT);
  terminalProc = spawn(python, [TERMINAL_SCRIPT], {
    stdio: 'ignore',
    shell: IS_WIN,
    detached: false,
  });
  terminalProc.on('error', err => console.warn('[terminal]', err.message));
}

// ════════════════════════════════════════════════════════════════════════════
// Create the main window
// ════════════════════════════════════════════════════════════════════════════
function createWindow() {
  mainWindow = new BrowserWindow({
    width:     1400,
    height:    900,
    minWidth:  900,
    minHeight: 600,
    title: 'Lucy OS v5',
    backgroundColor: '#0a0a0f',
    show: false,
    frame: true,
    titleBarStyle: IS_WIN ? 'default' : 'hiddenInset',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      webSecurity:      false,  // Allow fetch to localhost:3001, 8765, 8766
    },
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
  });

  const loadMode = getLoadMode();
  console.log('[electron] Load mode:', loadMode.mode);

  if (loadMode.mode === 'vite') {
    mainWindow.loadURL(loadMode.url);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else if (loadMode.mode === 'file') {
    mainWindow.loadFile(loadMode.file);
  } else {
    // No dist, not in dev — show inline error page
    mainWindow.loadURL(`data:text/html,<html style="background:#0a0a0f;color:#00ffcc;font-family:monospace;padding:40px">
      <h2>&#128274; Lucy OS — Build Required</h2>
      <p>${loadMode.message}</p>
      <p>Run <code>START.bat</code> and choose <strong>[1]</strong> to build and launch,<br>
      or <strong>[4]</strong> for hot-reload dev mode.</p>
    </html>`);
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ════════════════════════════════════════════════════════════════════════════
// System tray
// ════════════════════════════════════════════════════════════════════════════
function createTray() {
  try {
    const iconPath = path.join(__dirname, '..', 'assets', 'tray-icon.png');
    const icon = fs.existsSync(iconPath)
      ? nativeImage.createFromPath(iconPath)
      : nativeImage.createEmpty();

    tray = new Tray(icon);
    tray.setToolTip('Lucy OS v5');

    const menu = Menu.buildFromTemplate([
      { label: 'Open Lucy OS',  click: () => { mainWindow?.show(); mainWindow?.focus(); } },
      { label: 'Bridge Status', click: () => showStatus() },
      { type: 'separator' },
      { label: 'Quit Lucy OS',  click: () => { app.isQuitting = true; app.quit(); } },
    ]);

    tray.setContextMenu(menu);
    tray.on('click', () => { mainWindow?.show(); mainWindow?.focus(); });
  } catch (e) {
    console.warn('[electron] Tray creation failed:', e.message);
  }
}

function showStatus() {
  const lines = [
    `Lucy Server:  ${lucyReady   ? 'Running ✓' : 'Offline ✗'}  (port ${LUCY_PORT})`,
    `Bridge:       ${bridgeReady ? 'Running ✓' : 'Offline ✗'}  (port ${BRIDGE_PORT})`,
    `Terminal:     ${terminalProc ? 'Running ✓' : 'Offline ✗'}  (port ${TERMINAL_PORT})`,
  ];
  dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Lucy OS — Service Status',
    message: lines.join('\n'),
  });
}

// ════════════════════════════════════════════════════════════════════════════
// IPC handlers (React → Electron)
// ════════════════════════════════════════════════════════════════════════════
ipcMain.handle('bridge:status', () => ({
  running:     bridgeReady,
  lucyRunning: lucyReady,
  port:        BRIDGE_PORT,
  lucyPort:    LUCY_PORT,
  pid:         bridgeProc?.pid ?? null,
}));

ipcMain.handle('bridge:restart', async () => {
  if (bridgeProc) { bridgeProc.kill(); bridgeProc = null; bridgeReady = false; }
  return await startBridge();
});

ipcMain.handle('app:version', () => app.getVersion());

// ════════════════════════════════════════════════════════════════════════════
// App lifecycle
// ════════════════════════════════════════════════════════════════════════════
app.whenReady().then(async () => {
  // Start backends concurrently, then open window
  await Promise.all([
    startLucyServer(),
    startBridge(),
  ]);
  startTerminal();  // fire-and-forget

  createWindow();
  createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else mainWindow?.show();
  });
});

app.on('window-all-closed', () => {
  // Stay in tray — don't quit
});

app.on('before-quit', () => {
  app.isQuitting = true;
  const procs = [bridgeProc, terminalProc, lucyProc].filter(Boolean);
  for (const proc of procs) {
    try {
      if (IS_WIN) {
        spawn('taskkill', ['/pid', String(proc.pid), '/f', '/t'], { stdio: 'ignore' });
      } else {
        proc.kill('SIGTERM');
      }
    } catch {}
  }
});

app.on('web-contents-created', (_, contents) => {
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
});