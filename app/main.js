// Project IGI Studio, the desktop app.
//
// The studio is a local server (the Python package in ../studio) and a page it
// serves (../editor). This window is what ties them into one program:
//
//   1. start the server for this window alone: a free port it picks itself,
//      and a random token handed over on stdin, so it never shows in a process
//      list;
//   2. wait for the line it prints when it is listening (STUDIO_READY port=N);
//   3. open the editor, adding the token to every request the window makes.
//      The server refuses anything without it, so no other program on the
//      machine, and no web page in a browser, can drive the studio;
//   4. stop the server when the window closes.
//
// It also looks for a new version of itself, unless told not to (updates.js).
//
// The page gets no Node: context isolation on, sandboxed, and the only things
// it can ask of this process are in preload.js.
'use strict';

const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const updates = require('./updates');

const TITLE = 'Project IGI Studio';
const token = crypto.randomBytes(32).toString('hex');
let server = null;
let port = null;
let win = null;
let quitting = false;
let logStream = null;

// ------------------------------------------------------------------ the log
// What the server says goes to a file in the app's own folder, so a problem
// can be reported with the log attached (Help, Open the log folder).
function logFile() {
  return path.join(app.getPath('userData'), 'logs', 'studio.log');
}

function log(text) {
  try {
    if (!logStream) {
      fs.mkdirSync(path.dirname(logFile()), { recursive: true });
      logStream = fs.createWriteStream(logFile(), { flags: 'w' });
    }
    logStream.write(String(text));
  } catch (e) {
    // a log that cannot be written must not stop the studio
  }
}

// ------------------------------------------------------------------ the server
function serverCommand() {
  const args = ['serve', '--port', '0', '--token-stdin', '--no-browser'];
  if (app.isPackaged) {
    // the bundled server, built with PyInstaller: no Python needed
    const dir = path.join(process.resourcesPath, 'server');
    return { cmd: path.join(dir, 'studio-server.exe'), args, cwd: dir };
  }
  // from a checkout: the package beside this folder, with the Python on PATH
  const root = path.resolve(__dirname, '..');
  return { cmd: process.env.STUDIO_PYTHON || 'python', args: ['-m', 'studio'].concat(args), cwd: root };
}

function startServer() {
  return new Promise((resolve, reject) => {
    const { cmd, args, cwd } = serverCommand();
    log(`starting ${cmd} ${args.join(' ')}\n`);
    try {
      server = spawn(cmd, args, {
        cwd,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' }),
      });
    } catch (e) {
      reject(e);
      return;
    }
    server.stdin.write(token + '\n');
    server.stdin.end();

    let seen = '';
    const timer = setTimeout(() => reject(new Error('the studio did not start within 90 seconds')), 90000);
    server.stdout.on('data', (d) => {
      log(d);
      if (port) return;
      seen += d.toString();
      const m = seen.match(/STUDIO_READY port=(\d+)/);
      if (m) {
        port = Number(m[1]);
        clearTimeout(timer);
        resolve(port);
      }
    });
    server.stderr.on('data', log);
    server.on('error', (e) => { clearTimeout(timer); reject(e); });
    server.on('exit', (code) => {
      log(`\nthe server stopped (${code})\n`);
      if (!port) {
        clearTimeout(timer);
        reject(new Error(`the studio stopped while starting (exit ${code})`));
      } else if (!quitting) {
        serverLost(code);
      }
    });
  });
}

function stopServer() {
  if (server && server.exitCode === null) {
    try { server.kill(); } catch (e) { /* already gone */ }
  }
}

function serverLost(code) {
  const choice = dialog.showMessageBoxSync(win, {
    type: 'error',
    title: TITLE,
    message: 'The studio stopped working.',
    detail: `Its server ended (exit ${code}). Your missions are saved as you go, so nothing ` +
            'you did before the last save is lost. The log may say why.',
    buttons: ['Restart', 'Open the log folder', 'Quit'],
    defaultId: 0,
  });
  if (choice === 0) {
    app.relaunch();
    app.exit(0);
  } else if (choice === 1) {
    shell.openPath(path.dirname(logFile()));
    app.quit();
  } else {
    app.quit();
  }
}

// ------------------------------------------------------------------ the window
function origin() {
  return `http://127.0.0.1:${port}`;
}

function lockSession() {
  const ses = session.defaultSession;
  // the token rides on every request this window makes to its own server
  ses.webRequest.onBeforeSendHeaders({ urls: [origin() + '/*'] }, (details, done) => {
    details.requestHeaders['X-Studio-Token'] = token;
    done({ requestHeaders: details.requestHeaders });
  });
  // no camera, microphone, location, notifications or anything else; the 3D
  // view may hold the mouse, as a game's camera does (pointer lock)
  ses.setPermissionRequestHandler((wc, permission, done) =>
    done(permission === 'clipboard-sanitized-write' || permission === 'pointerLock'));
}

function createWindow() {
  win = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    title: TITLE,
    backgroundColor: '#08180a',
    icon: path.join(__dirname, 'build', 'icon.png'),
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });
  win.once('ready-to-show', () => win.show());
  win.removeMenu();
  keys(win.webContents);

  // the studio never opens windows of its own, and never navigates away: a
  // link out of it goes to the browser instead
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url) && !url.startsWith(origin())) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(origin())) {
      e.preventDefault();
      if (/^https?:\/\//.test(url)) shell.openExternal(url);
    }
  });

  win.loadURL(origin() + '/plotter.html');
}

// No menu bar. Electron shows a hidden one whenever Alt is pressed, which
// pushed the whole studio down and back up during every Alt+drag in the 3D
// view; everything it held is in the studio's own menu now (preload.js). Its
// keys stay: zoom, full screen, reload, and the developer tools in a checkout.
function keys(wc) {
  wc.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    const ctrl = input.control || input.meta, k = input.key;
    let used = true;
    if (ctrl && (k === '=' || k === '+')) wc.setZoomLevel(Math.min(4, wc.getZoomLevel() + 0.5));
    else if (ctrl && k === '-') wc.setZoomLevel(Math.max(-4, wc.getZoomLevel() - 0.5));
    else if (ctrl && k === '0') wc.setZoomLevel(0);
    else if (k === 'F11') win.setFullScreen(!win.isFullScreen());
    else if (k === 'F5' || (ctrl && !input.shift && k.toLowerCase() === 'r')) wc.reload();
    else if (!app.isPackaged && ctrl && input.shift && k.toLowerCase() === 'i') wc.toggleDevTools();
    else used = false;
    if (used) e.preventDefault();
  });
}

function about() {
  return dialog.showMessageBox(win, {
    title: TITLE,
    message: `${TITLE} ${app.getVersion()}`,
    detail: "A mission studio for Project I.G.I.: I'm Going In.\n" +
            'It ships no game files: everything it needs is made on your ' +
            'machine from your own copy of the game.\n\nMIT licensed. Made by Nouman Ahsan.',
  });
}

function studioHome() {
  return process.env.IGISTUDIO_HOME || path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'ProjectIGIStudio');
}

// ------------------------------------------------------------------ what the page may ask
ipcMain.handle('studio:version', () => app.getVersion());

// Settings, Updates: whether to look for a new version at start, and a way to look now
ipcMain.handle('studio:updates-get', () => updates.state());
ipcMain.handle('studio:updates-set', (e, on) => updates.setEnabled(on === true));
ipcMain.handle('studio:updates-check', () => { updates.check(true); return true; });

// what the menu bar used to hold, asked for from the studio's own menu
ipcMain.handle('studio:open-logs', () => shell.openPath(path.dirname(logFile())));
ipcMain.handle('studio:open-home', () => shell.openPath(studioHome()));
ipcMain.handle('studio:about', () => { about(); return true; });

ipcMain.handle('studio:pick-folder', async (e, title) => {
  const r = await dialog.showOpenDialog(win, {
    title: typeof title === 'string' ? title.slice(0, 120) : 'Choose a folder',
    properties: ['openDirectory'],
  });
  return r.canceled || !r.filePaths.length ? null : r.filePaths[0];
});

// opens a folder in Explorer: only ever a folder, never a file, which could
// be a program
ipcMain.handle('studio:open-folder', async (e, p) => {
  if (typeof p !== 'string' || !p) return false;
  try {
    if (!fs.statSync(p).isDirectory()) return false;
  } catch (err) {
    return false;
  }
  return (await shell.openPath(p)) === '';
});

// ------------------------------------------------------------------ start and stop
if (!app.requestSingleInstanceLock()) {
  // one studio at a time: a second start brings the first one forward
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    try {
      await startServer();
    } catch (e) {
      dialog.showErrorBox(TITLE, `The studio could not start.\n\n${e.message}\n\nThe log is in ${logFile()}`);
      app.quit();
      return;
    }
    lockSession();
    createWindow();
    updates.start({ window: () => win, log });
  });

  app.on('before-quit', () => { quitting = true; stopServer(); });
  app.on('window-all-closed', () => app.quit());
  process.on('exit', stopServer);
}
