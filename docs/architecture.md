# How the studio is put together

The layout of the repository, the desktop app around it, what happens when a
game is connected, and where everything the studio makes is kept.

## The repository

```
project-igi-studio/
├── editor/                 the 2D mission editor (also published as a claude.ai Artifact)
│   ├── plotter.html        the page: vanilla JS + Canvas 2D, no build step
│   ├── ai.js               the AI designer panel: chats, pictures, the model's tools
│   ├── icons.js            SVG-path icons: guards, player, pickups, vehicles, trees, fittings
│   ├── meshes.js           top-down renders of the game's own models (buildings, towers, props)
│   ├── view3d.js, fx.js    the 3D close-up, and the map computer's zoom transition
│   └── vendor/             three.js
├── studio/                 the Python package  (python -m studio)
│   ├── protect.py          the one gate for writes: built-in missions are never touched
│   ├── qvm/                the game's script format, ours end to end
│   │   ├── read.py         .qvm to instructions, and back to .qsc source
│   │   ├── write.py        .qsc source to .qvm bytecode
│   │   ├── qsc.py          the .qsc lexer and parser
│   │   ├── compile.py      compile and decompile as the rest of the studio uses them
│   │   ├── corpus.py       capture the game's own scripts to test against
│   │   ├── check.py        our reader and writer against that corpus, byte for byte
│   │   └── toolkit.py      the old third party pipeline, kept only to capture a corpus
│   ├── build/              turning a plan into a level the game can load
│   │   ├── plan.py         plan JSON -> objects.qsc, AI scripts, edited graphs (validates first)
│   │   ├── install.py      put a built mission into its slot: script, models, ground, strings, graphs
│   │   ├── slots.py        game mission slots: create from a base level, name, remove
│   │   ├── graphs.py       read / add, move, remove nodes / rebuild routing / write graph*.dat
│   │   ├── navtemplates.py interior navmesh (floors, stairs, doors) of every building a level ships
│   │   ├── flatten.py      level ground under new buildings with terrain height maps
│   │   ├── surface.py      what a placed object stands on, and whether a walk passes through a wall
│   │   ├── terrain.py      exact terrain height from terrain.ctr/.cmd/.hmp
│   │   ├── models.py       pack models from other levels into a slot; verify / repair / restore
│   │   ├── lang.py         the game's text resources: a mission's objective texts and labels
│   │   ├── empty_map.py    a built-in level reduced to terrain, sky, weather, navmesh, player
│   │   └── migrate.py      turn a slot built the old way into a custom mission
│   ├── extract/            reading the game's own files into what the editor needs
│   │   ├── levels.py       level scripts -> levelN.json in the level data
│   │   ├── graphs.py       graph*.dat -> node positions + routing facts
│   │   ├── models.py       model footprints, map labels, per-level model availability
│   │   ├── meshes.py       every structure's render mesh, for drawing it from above
│   │   ├── terrain.py      each level's terrain as a 1 m height grid for the editor
│   │   ├── ground.py       what the ground is made of, from the level's texture masks
│   │   ├── catalog.py      inventory: every structure, weapon and enemy type in the game
│   │   ├── library.py      in-game covers, names and map types of the 14 missions
│   │   └── model3d.py      textured models for the editor's 3D close-up
│   └── server/             what the editor talks to
│       ├── app.py          local server: editor, mission library API, Apply, Settings
│       ├── ai.py           the AI designer's proxy: the API key, the models, streaming
│       ├── missions.py     custom missions: base + plan, history, trash (missions/custom/)
│       └── live_pos.py     find and read the player's live position in a running game
├── app/                    the desktop app: the Electron window, the installer, the bundled server
├── docs/                   plans for larger changes, and docs/PLAN-ship.md, the road to 1.0
├── missions/
│   ├── custom/<id>/        your missions: mission.json, cover.png, history/
│   └── groups/             saved groups (reusable sets of objects)
└── plans/                  plan JSON from before missions had a base (kept for reference)
```

## The desktop app

**What it is.** A window (Electron) around the same studio you can run from a
checkout. It starts the studio's server for itself alone, on a free port, and
hands it a random token nobody else knows; every request the window makes
carries it, and the server refuses anything without it. The page gets no
access to the machine beyond a folder picker. The API key you type in
Settings is encrypted for your Windows account (DPAPI) and is never written to
the settings file.

**Building it.** From `app/`:

```
npm install
npm run dist        the bundled server, then the installer and the zip in app/dist
npm start           the window around a checkout, using the Python on PATH
```

`npm run dist` bundles the server with PyInstaller in its own virtual
environment (`app/build-server`), so nothing is installed into your Python.

## Setup

You need your own copy of Project I.G.I. and Python 3. Nothing else: the
studio compiles the game's scripts itself, and ships no game files.

The first time it runs it asks where the game is, and offers what it found:
the registry's uninstall entries, GOG's and Steam's own records, and the usual
folders. From a terminal the same thing is:

```
python -m studio setup                    what it knows and what it needs
python -m studio setup --find             copies of the game on this machine
python -m studio setup --game <folder>    use that one (it is checked first)
python -m studio setup --snapshot         keep our own copy of the level data
python -m studio setup --check-game       has anything in the built-in missions drifted
python -m studio setup --repair           put the drifted ones back
```

- **Checking.** The files a mission is built from are hashed into one
  fingerprint, so the studio can say which build you have, or say plainly that
  it does not know this one and which known build it is closest to. It works
  either way: missions are built from your game, whatever it is.
- **The reference copy, made before anything else.** The moment you connect a
  game, and before the studio writes a single byte into it, it copies the
  parts a mission is rebuilt from into
  `%LOCALAPPDATA%\ProjectIGIStudio\pristine` and checks every file against the
  one it came from: about 167 MB of level scripts, AI scripts, graphs,
  terrain, language files and each level's model archive (the buildings'
  meshes, which say whether a crate stands on a roof or on the ground). If that
  copy fails, the game is not connected. Every later build reads levels from
  the copy, never from the game it writes to, and a build from the copy is
  byte for byte the build from the game. Textures, sounds and lightmaps are not
  copied: no build reads them.
- **One game is written to.** The studio writes into the game you connected
  and nowhere else: a custom mission slot anywhere else on the disk is refused
  by `studio/protect.py`, along with every built-in mission and the reference
  copy itself. Outside its slots it writes only a mission's strings into the
  two language files, and the game's `config.qvm`: the game only offers the
  missions a player has reached (`GOActiveMission(N)`, 1 on a fresh install),
  so `studio/build/unlock.py` raises N to each slot applied, never lowering it,
  and again just before the studio starts the game.
- **Which slot holds which mission is the game's to say.** Every slot the
  studio fills carries a marker naming its mission, and the server reads the
  connected game's markers (`held_by_game`) rather than trusting the slot
  number a mission last had: after switching to another copy of the game,
  that number is somebody else's slot, or none. Switching games goes through
  the setup's job (`POST /api/setup/game`), which copies the new game's levels
  first; the server refuses a bare change of the game folder.
- **Drift.** *Check the built-in missions* compares them with that copy.
  Putting one back is the only write to a built-in mission the studio allows,
  and it can only restore the original bytes. A deliberate change is
  recognised and left alone: mission 14 pointing at mission 15 is how a custom
  mission is reached from the campaign.
- **Your things** (settings, missions, chats) live in
  `%LOCALAPPDATA%\ProjectIGIStudio`. A checkout keeps using its own
  `config.json`, so working on the project never touches an installed copy's
  settings. `IGISTUDIO_HOME` moves the folder, which is what the tests use.
- **Where your work lives.** A mission is yours, not the game's: its plan,
  name, cover, history and chats are in the studio's folder
  (`%LOCALAPPDATA%\ProjectIGIStudio\missions`, or `missions/custom` in a
  checkout). The game only receives what Apply builds from it: the compiled
  mission in its slot, and its strings. Every Apply also writes the whole
  mission, plan and all, into the slot's marker file, so the game carries a
  copy of everything it was given.
- **When something goes missing.**
  - *The game folder is gone* (a drive unplugged, the game moved or
    uninstalled): the studio says so, names the folder, and keeps working.
    Your missions open and edit as before, because the levels are read from
    the reference copy. Only Apply and launching need the game, and Apply
    refuses with a sentence saying why, having written nothing.
  - *The studio's folder is gone* (a new machine, a wiped profile): connect
    the game again and the setup lists the missions the game is carrying;
    *Bring them back* restores them, plan and all. A mission already in the
    studio is never overwritten by the copy in the game.
  - *The reference copy is gone*: the next Apply makes it again from the game,
    checks it, and only then builds.
- For the AI designer: an OpenAI API key in `.env` (`OPENAI_API_KEY=...`,
  optionally `MODEL_QUALITY=<model>`), or typed in Settings. Nothing else to
  install: the server talks to the API with Python's own `urllib`.

Don't edit a level with the IGI ToolKit GUI afterwards. It rebuilds
`objects.qvm` from its own master copy and discards anything changed outside
it.

## The level data

The editor draws the fourteen levels, their walkways, their ground and their
buildings. All of that comes out of the game, so none of it is in this
repository or in the program: it is built on your machine, from your own copy
of the game, into `%LOCALAPPDATA%\ProjectIGIStudio\data`, when you connect the
game. It takes a minute or two. To build it again:

```
python -m studio setup --data
```

In order: the levels' objects, the walkways, every model's size and name, the
inventory, the ground's height (on a 1 m grid), what the ground is made of, the
buildings seen from above, the walkways inside buildings, and the missions'
names and covers. Most of it is read from the reference copy; the shared model
archive, the terrain textures and the menu's covers are only in the game and
are read from there. Level 14 has no height map in the game, so it has no
ground grid (as it never had).

The editor asks for `data/...` beside the page, and the server answers from
that folder, so the editor does not know or care where the data came from.

## Not in the repo

No game files and nothing derived from them: the level data, the decompiled
scripts, the reference copy, the backups of the game's own files, the caches,
and the corpus the compiler is tested against. All of it is made on your
machine from your own copy of the game. Your own things are not in it either:
settings, missions, saved groups and conversations with the AI designer.
