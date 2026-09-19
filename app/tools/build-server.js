// Builds the bundled server (app/dist-server/studio-server) with PyInstaller,
// so the installed studio needs no Python.
//
//   node tools/build-server.js        (npm run server)
//
// PyInstaller lives in its own virtual environment under app/build-server, so
// nothing is installed into the Python on this machine.
'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const APP = path.resolve(__dirname, '..');
const ROOT = path.resolve(APP, '..');
const WORK = path.join(APP, 'build-server');
const VENV = path.join(WORK, '.venv');
const PY = path.join(VENV, 'Scripts', 'python.exe');
const OUT = path.join(APP, 'dist-server');

function run(cmd, args, opts) {
  console.log('> ' + [path.basename(cmd)].concat(args).join(' '));
  execFileSync(cmd, args, Object.assign({ stdio: 'inherit', cwd: ROOT }, opts || {}));
}

if (!fs.existsSync(PY)) {
  fs.mkdirSync(WORK, { recursive: true });
  run(process.env.STUDIO_PYTHON || 'python', ['-m', 'venv', VENV]);
  run(PY, ['-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'pyinstaller']);
}

const sep = ';';                        // PyInstaller's --add-data separator on Windows
const data = [
  [path.join(ROOT, 'editor'), 'editor'],
  [path.join(ROOT, 'studio', 'extract', 'model_names.json'), 'studio/extract'],
  [path.join(ROOT, 'studio', 'setup', 'profiles.json'), 'studio/setup'],
  [path.join(ROOT, 'LICENSE'), '.'],
  [path.join(ROOT, 'THIRD-PARTY-NOTICES.md'), '.'],
];
const args = [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
  '--name', 'studio-server', '--onedir', '--console',
  '--icon', path.join(APP, 'build', 'icon.ico'),
  '--distpath', OUT, '--workpath', path.join(WORK, 'work'), '--specpath', WORK,
  '--paths', ROOT,
  // the studio runs most of its modules by name, which PyInstaller cannot see
  '--collect-submodules', 'studio',
];
for (const [src, dst] of data) args.push('--add-data', src + sep + dst);
args.push(path.join(__dirname, 'server_entry.py'));
run(PY, args);

const exe = path.join(OUT, 'studio-server', 'studio-server.exe');
if (!fs.existsSync(exe)) throw new Error('PyInstaller did not produce ' + exe);
// it has to run a module by name (how the studio calls its builder); the key
// store's self-test does that, and proves Windows' encryption works bundled
const env = Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' });
console.log(execFileSync(exe, ['-m', 'studio.keystore'], { env, encoding: 'utf-8' }).trim());
console.log('built ' + exe);
