# Shipping Project IGI Studio

The plan that turns this working prototype into something a stranger can
install and use. Written 2026-09-19.

**The goal:** a signed Windows installer. You run it, it finds or asks for your
copy of the game, checks it, prepares what it needs, and the studio opens. No
Python, no third party toolkit, no manual steps.

## Decisions taken

| Question | Answer |
|---|---|
| Product name | **Project IGI Studio** (window title, installer, docs, site) |
| Repository | `github.com/NaumanHSA/project-igi-studio`, private until 1.0 |
| Licence | MIT |
| Shell | Electron, with the Python backend as a bundled sidecar |
| UI framework | No rewrite. Modularise with Vite after 1.0, React only if a panel earns it |
| The game | Never shipped. Found, checked and snapshotted on the user's machine |
| Game versions | The current (modded) install first, stock retail and GOG after |
| Compiler | Ours. The IGI ToolKit dependency goes away completely |
| Signing | Unsigned while private, SignPath Foundation (free, open source) at 1.0 |
| Site | Landing page and manual, one site on GitHub Pages, in a repository of its own (`project-igi-studio-site`) |

## What we never ship

Game files, game-derived data (terrain, meshes, graphs, decompiled scripts),
third party binaries. Everything derived from the game is produced on the
user's machine from the user's own install. This is both the legal line and
the reason the download stays small.

## Phases

### Phase 0: the corpus (do first, while the ToolKit is installed)  (done 2026-09-19)

The ToolKit is the only thing that knows what correct output looks like, so
capture that knowledge before replacing it.

- `studio/qvm/corpus.py` walks the pristine game, and for every shipped script
  keeps the original `.qvm`, the ToolKit's decompilation of it, and the
  ToolKit's recompilation of that decompilation.
- A manifest records sizes and hashes, so a corpus can be rebuilt and compared
  on any machine that has the ToolKit.
- The corpus is gitignored (it is game-derived) and regenerable.

**Done when** the corpus covers every level's `objects.qvm`, `mission.qvm` and
AI scripts, and the manifest is stable across two runs.

### Phase 1: repository hygiene  (done 2026-09-19)

- Archive `project-igi-editor` and `project-igi-editor-3.6.11-pre` out of the
  workspace; keep `IGIToolKit_v0.8.7.5` archived as the oracle until Phase 3
  passes; move the second, untouched install out of the
  workspace.
- `LICENSE` (MIT), a short `README.md` pointing at the site, `CONTRIBUTING.md`,
  issue templates, `.editorconfig`.
- Rename the product to Project IGI Studio in the UI, the server and the docs.
- Folders: `editor/` and `docs/` keep their names, and the flat `tools/` pile
  of 32 scripts becomes the `studio` package: `studio.qvm` (the script format),
  `studio.build` (making a mission), `studio.extract` (reading the game),
  `studio.server` (what the editor talks to), with `python -m studio` as the
  one way in. Add `app/` for Electron and `site/` for the website. `docs/`
  stays the design notes, `site/` holds the user manual.
- Audit what git tracks. `editor/data` is game-derived and must leave the repo
  in Phase 4; until then it stays, which is why the repo stays private.

**Done when** the workspace holds the repo and `notes.txt`, the remote is the
renamed repo, and the studio still runs and applies a mission.

### Phase 2: first run and configuration  (done 2026-09-19)

- Find the game: registry, GOG, Steam, common paths, then ask.
- Fingerprint it: hash the files we depend on, match against known profiles,
  name the profile in the UI, and refuse politely on an unknown build rather
  than producing a broken mission. The current modded install is profile A.
- Make our own pristine snapshot under `%LOCALAPPDATA%\ProjectIGIStudio`, so
  the studio always has a clean base even if the user later mods their game.
- No hardcoded `D:\` anywhere. `config.json` moves to the user's app data, and
  missions with it.

**Done when** a fresh machine with only the game can be pointed at it and the
studio works, with `config.json` deleted beforehand.

### Phase 3: our own QVM compiler (the 1.0 gate)  (done 2026-09-19)

Today: `objects.qsc` goes to QVM v7 through `gconv.exe`, then to QVM v5 through
`dconv.exe`, both third party.

**A large head start, found 2026-09-19:** `project-igi-editor` (HeavenHM),
which was sitting next to this project as a reference copy, is **MIT licensed**
and carries a complete QVM parser, decompiler and compiler in C++ (about 2,300
lines), a QSC lexer and parser, a round trip test, and a written format
specification: the 60 byte `LOOP 8.5` header, both string pools, and all 49
opcodes. MIT lets us port it, so Phase 3 becomes a port plus hardening rather
than reverse engineering from bytes. Their own tests only compare normalised
text, so **our corpus holds ours to a higher standard: byte equality with the
game's own files**, which we know is reachable because the ToolKit's round trip
is byte exact (39 of 39 on level 1).

Attribution: the port keeps their copyright notice in
`THIRD-PARTY-NOTICES.md` and in the header of each ported file, as MIT
requires. The C++ reference copy is kept outside this repository.

- **Reader first** (`studio/qvm/read.py`): QVM v5 to QSC. Validated against the
  corpus: every shipped script must read, and the result must match the
  ToolKit's decompilation token for token.
- **Writer second** (`studio/qvm/write.py`): QSC straight to QVM v5, no v7 stop
  on the way. Validated by byte comparison against the corpus, then by
  launching a built mission in the game.
- The writer only has to emit what the studio generates, which is a narrow
  subset. The reader has to understand everything the game ships.
- `compile_qsc.py` keeps its interface and swaps its insides, so nothing above
  it changes.

**Done when** reader and writer pass on 100% of the corpus, a mission built
entirely with our compiler plays, and the ToolKit can be uninstalled.

### Phase 4: data generated on the user's machine  (done 2026-09-19)

- The extraction pipeline (`extract_levels`, `build_ground`, `build_meshes`,
  `build_catalog`, `parse_graphs`, `build_terrain`, `build_navtemplates`) runs
  as a first run step with a progress bar, writing into app data.
- `editor/data` leaves the repo.
- The decompiled scripts the builder needs come from the user's own game
  through our Phase 3 reader.

**Done when** a clone of the repo contains no game-derived byte, and first run
produces everything the editor needs in a few minutes.

### Phase 5: the desktop app  (done 2026-09-19)

- `app/`: Electron main process, preload with `contextIsolation`, no
  `nodeIntegration`. It starts the Python sidecar on a free port with a random
  per launch token, waits for `/api/status`, and loads the editor.
- The API requires that token, so nothing else on the machine can drive it.
- The OpenAI key moves from `.env` to the OS credential store through Electron
  `safeStorage`.
- Python is bundled with PyInstaller (pin 3.12 if 3.14 is unsupported).
- `electron-builder` produces an NSIS installer and a portable zip.
- Auto update through `electron-updater` once releases are public.

**Done when** the installer runs on a machine with no Python and no ToolKit,
and builds a mission.

How it went:

- The key store is `studio/keystore.py`, DPAPI through ctypes, rather than
  Electron's safeStorage. On Windows they are the same mechanism, and doing it
  in Python keeps one path for the app and a checkout run by hand.
- PyInstaller 6.22 supports Python 3.14, so nothing had to be pinned. The
  bundled server is 24 MB; the installer 120 MB, the zip 164 MB (Electron is
  most of it).
- The server sends a Content Security Policy, and the editor's fonts are
  bundled, so it works offline and asks no one for anything.
- Tested: the bundled server with no Python on its PATH connected a game,
  built a mission and applied it (to a throwaway copy of the game); the
  installer installed silently, the installed app walked a new user from the
  setup screen to the library with all fourteen missions, and the uninstaller
  removed the program and its entries and kept the user's folder.
- Auto update came in Phase 7; signing waits for SignPath.

### Phase 6: the site  (done 2026-09-19, bar publishing it)

- One VitePress site: a landing page (map computer theme, green phosphor,
  three.js hero built from our own generated terrain, not game data) and the
  manual behind a button.
- The manual: install, first run, your first mission, the map, objectives and
  events, guards and patrols, ground and walkways, the AI designer, applying
  and playing, troubleshooting, and a page for the SmartScreen warning.
- Screenshots are scripted through the DevTools harness that already drives the
  editor, so they regenerate every release and never go stale.

**Done when** the site builds in CI and every manual page has a current
screenshot.

Done, in a repository of its own: **`project-igi-studio-site`**, private
(decided 2026-09-19), so that the studio's public repository carries no
pictures of the game. It holds the landing page, the manual (fourteen pages,
50 pictures), the tool that takes the pictures from a checkout of the studio,
and a Deploy workflow that publishes it to GitHub Pages
(`naumanhsa.github.io/project-igi-studio-site/`), started by hand. Its README
says how.

Since then: a download page (`/download`, the latest release read from
GitHub, macOS and Linux marked as coming soon), who made it at the foot of
the landing page, and the code signing policy (`/signing`) SignPath asks for.
This repository's README is the public front page now; the developer's
reference it used to hold is in `docs/`. Left: publishing the site, which
goes out with the first release.

### Phase 7: public and signed

**Decided 2026-09-19:** the public repository starts fresh from one clean
commit. This repository was renamed `project-igi-studio-dev`, stays private,
and keeps the whole history; `project-igi-studio` is the public one.

- Scan the git history for secrets before the repo goes public.
- MIT licence in place, public repo, apply to SignPath Foundation, wire signing
  into the release workflow.
- Releases: tagged, with installer, portable zip, checksums and notes.

Done 2026-09-19:

- **The history is clean.** The public history (7 commits) holds no secrets
  and no game-derived byte in any version of any file. The local clone no
  longer carries the private history either: its branch and the `dev` remote
  are gone and the unreachable objects pruned (57 MB to 1 MB).
- **Releases build themselves.** `.github/workflows/release.yml`: a tag builds
  on Windows, checks that the tag, the app and the studio agree, and drafts
  the release with the installer, the zip, `SHA256SUMS.txt`, the updater's
  `latest.yml` and blockmap, and notes from `CHANGELOG.md`. Run by hand it is
  a dry run. PyInstaller is pinned, and `studio-server.exe` now carries the
  product name and version, as signing requires. The version is 1.0.0.
- **Updates.** `app/updates.js` (electron-updater, GitHub releases): an
  installed studio downloads a new version and installs it on close; the
  portable zip only says one is out. Settings, Updates turns the check off,
  and the privacy statement says what it sends (nothing about the user).
  Tested on the built app: the check runs, and a failed one is only logged.
- **The README** is a front page (banner, downloads, what's in the box, how
  it works, building it); the reference moved to `docs/editor.md`,
  `docs/architecture.md` and `docs/engine.md`, and `docs/releasing.md` says
  how to cut a release and what signing will change.
- **SignPath's conditions** (checked on signpath.org): an OSI licence, a
  release already out in the form to be signed, CI builds, MFA for the team,
  product name and version on every signed file, a policy page with roles and
  a privacy statement, and a manual approval per release. So 1.0 goes out
  unsigned, and signing follows.

Left, in order:

1. The owner's read of the site and the manual.
2. A dry run of the release workflow on GitHub (Actions, Release, Run
   workflow), to see it build on a clean Windows machine.
3. **Going public**, all on the same day: make this repository public, run
   the site's Deploy workflow, push the tag `v1.0.0`, read the draft release
   and publish it.
4. Apply to SignPath Foundation, then add signing to the workflow
   (`docs/releasing.md`, Signing).
5. Test on an unmodified copy of the game (GOG or Steam) when one is to hand.

### Phase 8: after 1.0

Vite and ES modules for the editor, React for panels only if it pays, a plugin
seam for new tools, and the stock and GOG game profiles.

## Risks

- **Unknown QVM opcodes.** Mitigated by the corpus: anything the game ships
  must read, and anything that does not read is a known gap before release.
- **Everything we extracted came from a modded install.** Phase 2's
  fingerprinting makes that explicit instead of silent.
- **PyInstaller and Python 3.14.** If unsupported, the build pins 3.12.
- **Unsigned first releases.** Documented with the exact clicks; SignPath
  needs a release out before it signs, so signing follows 1.0. Unsigned
  PyInstaller programs are sometimes flagged by antivirus heuristics; signing
  is the cure for that too.
- **The corpus cannot be recreated** if the ToolKit disappears. It is archived
  alongside, and the manifest records what it contained.
