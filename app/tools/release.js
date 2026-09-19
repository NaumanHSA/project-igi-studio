// What a release needs besides the build. The release workflow
// (.github/workflows/release.yml) runs both; they work the same by hand.
//
//   node app/tools/release.js check [tag]   the tag, the app and the studio agree on the
//                                           version, and CHANGELOG.md has a section for it
//   node app/tools/release.js assemble      after npm run dist: app/dist/release holds the
//                                           files to publish and SHA256SUMS.txt, and
//                                           app/dist/NOTES.md the release notes
//
// SIGNED=1 in the environment leaves out the notes' SmartScreen warning, for
// releases signed through SignPath.
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const APP = path.resolve(__dirname, '..');
const ROOT = path.resolve(APP, '..');
const DIST = path.join(APP, 'dist');
const OUT = path.join(DIST, 'release');
const REPO = 'https://github.com/NaumanHSA/project-igi-studio';
const SITE = 'https://naumanhsa.github.io/project-igi-studio-site';
const version = require(path.join(APP, 'package.json')).version;

function fail(msg) {
  console.error('release: ' + msg);
  process.exit(1);
}

function studioVersion() {
  const m = fs.readFileSync(path.join(ROOT, 'studio', '__init__.py'), 'utf-8').match(/__version__\s*=\s*"([^"]+)"/);
  return m ? m[1] : '(none)';
}

// this version's section of the changelog, without its heading
function notes() {
  const text = fs.readFileSync(path.join(ROOT, 'CHANGELOG.md'), 'utf-8').replace(/\r\n/g, '\n');
  const mine = text.split(/^## /m).slice(1).find((s) => s.split(/[\s(]/)[0] === version);
  return mine ? mine.slice(mine.indexOf('\n') + 1).trim() : null;
}

function check(tag) {
  const py = studioVersion();
  if (py !== version) fail(`app/package.json says ${version} but studio/__init__.py says ${py}`);
  // a run by hand is on a branch, not a tag: only a tag has to match
  if (tag && /^v\d/.test(tag) && tag !== 'v' + version) fail(`the tag is ${tag} but the version is ${version}`);
  if (!notes()) fail(`CHANGELOG.md has no section for ${version}`);
  console.log(`release: ${version}. The tag, the app and the studio agree, and the changelog has it.`);
}

const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const mb = (file) => Math.round(fs.statSync(file).size / 1048576) + ' MB';
const size = (file) => { const n = fs.statSync(file).size; return n < 1048576 ? Math.ceil(n / 1024) + ' KB' : mb(file); };

function assemble() {
  const setup = `ProjectIGIStudio-Setup-${version}.exe`;
  const zip = `ProjectIGIStudio-${version}-win.zip`;
  // latest.yml and the blockmap are what an installed studio reads to update itself
  const files = [setup, setup + '.blockmap', zip, 'latest.yml'];
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  for (const f of files) {
    if (!fs.existsSync(path.join(DIST, f))) fail(`the build did not make ${f} (is ${version} the version it built?)`);
    fs.copyFileSync(path.join(DIST, f), path.join(OUT, f));
  }
  const sums = [setup, zip].map((f) => `${sha256(path.join(OUT, f))}  ${f}`);
  fs.writeFileSync(path.join(OUT, 'SHA256SUMS.txt'), sums.join('\n') + '\n');

  const get = (f) => `${REPO}/releases/download/v${version}/${f}`;
  const body = [
    notes(),
    '',
    '## Download',
    '',
    '| File | What it is | Size |',
    '|---|---|---|',
    `| [${setup}](${get(setup)}) | The installer. Recommended | ${mb(path.join(OUT, setup))} |`,
    `| [${zip}](${get(zip)}) | The same program without an installer | ${mb(path.join(OUT, zip))} |`,
    '',
    'For Windows 10 and 11, 64-bit. You need your own copy of *Project I.G.I.: I\'m Going In*: the studio ships no game files. ' +
      `New here? The [manual](${SITE}/manual/install) walks you through it.`,
    '',
  ];
  if (process.env.SIGNED !== '1') {
    body.push(
      '> [!NOTE]',
      '> This release is not signed yet, so Windows SmartScreen may say it protected your PC. ' +
        `Choose **More info**, then **Run anyway**. The [code signing policy](${SITE}/signing) says why, and what changes.`,
      '',
    );
  }
  body.push('### SHA-256', '', '```', ...sums, '```', '');
  fs.writeFileSync(path.join(DIST, 'NOTES.md'), body.join('\n'));

  for (const f of fs.readdirSync(OUT)) console.log(`  ${f.padEnd(44)} ${size(path.join(OUT, f))}`);
  console.log(`release: ${version} assembled in ${path.relative(ROOT, OUT)}, notes in ${path.relative(ROOT, path.join(DIST, 'NOTES.md'))}`);
}

const [cmd, arg] = process.argv.slice(2);
if (cmd === 'check') check(arg);
else if (cmd === 'assemble') assemble();
else fail('say check [tag] or assemble');
