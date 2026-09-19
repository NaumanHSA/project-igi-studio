# Contributing

Thanks for looking. This is a mission editor for a game from 2000, so most of
the work is careful reverse engineering rather than web development.

## What you need

- Windows, Python 3.12 or newer, and your own copy of Project I.G.I.
- Node 20 or newer, for the desktop shell and the site.
- Nothing else. The studio never needs the game to be modded, and it never
  writes into the original install.

## Running it from source

```
python -m studio
```

Then open http://localhost:8765. The page probes `/api/status`, so the same
editor also runs as a plain static file, only without Apply.

## The desktop app

```
cd app
npm install
npm start           the window around this checkout
npm run dist        the bundled server, the installer and the zip, in app/dist
```

## The rules this project does not bend

1. **The original install is never written.** Every write goes through
   `studio/protect.py`, which refuses anything that is not a custom slot the
   studio created. If you need a new write path, add it there first.
2. **Built-in missions are never touched.** Levels 1 to 14 are the game's.
3. **No game files and no game-derived data in the repository.** Terrain,
   meshes, graphs and decompiled scripts are produced on the user's machine
   from the user's own game.
4. **A bad plan is refused with a sentence, not a crash.** The engine has hard
   limits (task ids, walkway distance, objective counts). The builder checks
   them and says what is wrong in plain English.

## Style

- Python: standard library only, no frameworks, four space indent.
- JavaScript: no build step in the editor, no dependencies beyond three.js.
- Text the user sees: plain sentences, no long dashes, and a tooltip is a
  title line then a line saying what it does.
- Comments explain why something is the way it is, especially where the engine
  forced it.

## Tests

The corpus tools compare our compiler against the game's own scripts:

```
python -m studio corpus --check      verify a captured corpus
python -m studio check                read and write every script in it
```

A change to the compiler that does not pass on 100% of the corpus does not go
in.

## Pull requests

Small and focused, with a note on what you tested. If it changes something the
user sees, update the manual page in `site/` too.
