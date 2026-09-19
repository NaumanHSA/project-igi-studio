// Updates. A few seconds after it starts, the studio asks GitHub whether a
// newer release exists, unless that is turned off in Settings (the choice is
// kept in the app's own folder, updates.json). Nothing about the user, the
// game or the missions is sent: it is the same request a browser makes to
// look at the releases page.
//
// An installed studio downloads a new version quietly and installs it when it
// closes, or at once if the user says so. The portable zip cannot replace
// itself, so it only says a new version is out and where to get it.
'use strict';

const { app, dialog, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const fs = require('fs');
const path = require('path');

const TITLE = 'Project IGI Studio';
const RELEASES = 'https://github.com/NaumanHSA/project-igi-studio/releases/tag/v';
const DOWNLOAD_PAGE = 'https://naumanhsa.github.io/project-igi-studio-site/download';
const DELAY = 8000;

let win = () => null;
let log = () => {};
let busy = false;
let told = '';          // the version already offered, so it is offered once
let ready = '';         // a version downloaded and waiting to install

function prefsFile() {
  return path.join(app.getPath('userData'), 'updates.json');
}

function enabled() {
  try {
    return JSON.parse(fs.readFileSync(prefsFile(), 'utf-8')).check !== false;
  } catch (e) {
    return true;
  }
}

function setEnabled(on) {
  fs.mkdirSync(path.dirname(prefsFile()), { recursive: true });
  fs.writeFileSync(prefsFile(), JSON.stringify({ check: !!on }));
  return !!on;
}

// the installer puts an uninstaller beside the program; the zip has none
function portable() {
  return !fs.existsSync(path.join(path.dirname(process.execPath), `Uninstall ${TITLE}.exe`));
}

function state() {
  return { check: enabled(), available: app.isPackaged, portable: app.isPackaged && portable(), version: app.getVersion() };
}

function message(opts) {
  const w = win();
  return w ? dialog.showMessageBox(w, Object.assign({ title: TITLE }, opts)) : dialog.showMessageBox(Object.assign({ title: TITLE }, opts));
}

async function offerPortable(version) {
  const r = await message({
    type: 'info',
    message: `Project IGI Studio ${version} is out.`,
    detail: `You have ${app.getVersion()}. This copy is the portable zip, which cannot update itself: ` +
            'download the new one and unpack it over this folder, or somewhere new. Your missions are not in it, so they stay.',
    buttons: ['Download page', "What's new", 'Later'],
    defaultId: 0,
    cancelId: 2,
  });
  if (r.response === 0) shell.openExternal(DOWNLOAD_PAGE);
  if (r.response === 1) shell.openExternal(RELEASES + version);
}

async function offerRestart(version) {
  const r = await message({
    type: 'info',
    message: `Project IGI Studio ${version} is ready to install.`,
    detail: `You have ${app.getVersion()}. It installs when you close the studio, or now if you restart it. ` +
            'Your missions, settings and level data are kept.',
    buttons: ['Restart now', 'When I close the studio', "What's new"],
    defaultId: 1,
    cancelId: 1,
  });
  if (r.response === 0) autoUpdater.quitAndInstall();
  if (r.response === 2) shell.openExternal(RELEASES + version);
}

/** Asks GitHub. By hand (Help, or Settings) it also says when there is nothing new, or why it could not ask. */
async function check(byHand) {
  if (!app.isPackaged) {
    if (byHand) message({ type: 'info', message: 'Updates come with the installed studio.', detail: 'A studio run from its source code is updated with git.' });
    return;
  }
  if (busy) return;
  busy = true;
  autoUpdater.autoDownload = !portable();
  try {
    const r = await autoUpdater.checkForUpdates();
    const next = r && r.updateInfo && r.updateInfo.version;
    const newer = next && r.isUpdateAvailable !== false && next !== app.getVersion();
    if (!newer) {
      if (byHand) message({ type: 'info', message: 'You have the latest version.', detail: `Project IGI Studio ${app.getVersion()}.` });
    } else if (portable() && (byHand || told !== next)) {
      told = next;
      offerPortable(next);
    } else if (!portable() && byHand) {
      if (ready === next) offerRestart(next);
      else message({ type: 'info', message: `Project IGI Studio ${next} is downloading.`, detail: 'The studio says when it is ready to install.' });
    }
  } catch (e) {
    log(`update check failed: ${e && e.message}\n`);
    if (byHand) message({ type: 'warning', message: 'The studio could not check for updates.', detail: 'GitHub could not be reached. The download page always has the latest version.' });
  } finally {
    busy = false;
  }
}

function start(opts) {
  win = opts.window;
  log = opts.log;
  autoUpdater.logger = { info: (m) => log(`update: ${m}\n`), warn: (m) => log(`update: ${m}\n`), error: (m) => log(`update: ${m}\n`), debug() {} };
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on('update-downloaded', (info) => {
    ready = info.version;
    if (told === info.version) return;
    told = info.version;
    offerRestart(info.version);
  });
  if (app.isPackaged && enabled()) setTimeout(() => check(false), DELAY);
}

module.exports = { start, check, state, setEnabled };
