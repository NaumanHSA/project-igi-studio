# Where everything lives. One place, so that no module has to guess at a path.
#
#   from studio import paths
#   paths.game()        the working copy of the game, the one the studio writes to
#   paths.pristine()    the untouched original, read to rebuild a mission from
#   paths.data()        the level data the editor loads
#
# Settings come from config.json at the root of the repository. When it says
# nothing, the fall-backs below are used, and they are the last place in the
# project that names a drive letter. The first run wizard (docs/PLAN-ship.md,
# phase 2) will write config.json instead, and move it to the user's app data.
import json, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where an installed copy keeps the settings, the missions and the snapshot.
#: IGISTUDIO_HOME overrides it, which is what the tests use.
APPNAME = "ProjectIGIStudio"


def home():
    """The user's own folder for this studio."""
    env = os.environ.get("IGISTUDIO_HOME")
    if env:
        return pathlib.Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return pathlib.Path(base) / APPNAME


def config_file():
    """The settings in use.

    A checkout keeps its own config.json beside the code, so working on the
    project never touches the installed copy's settings. An installed copy has
    no config.json there, and uses the one in the user's folder.
    """
    if os.environ.get("IGISTUDIO_HOME"):
        return home() / "config.json"
    local = ROOT / "config.json"
    if local.exists():
        return local
    return home() / "config.json"


CONFIG = config_file()

# Used only when the settings say nothing. A machine that has never run the
# setup has no game path at all, and game() then returns the empty path, which
# every caller reports as "the game has not been found yet" rather than
# guessing at a drive letter.
FALLBACK = {
    "gamePath": "",
    "pristinePath": "",
    "slot": 15,
}

_cache = {"mtime": None, "data": {}, "file": None}


def config():
    """The settings as a dict, re-read when they change on disk."""
    f = config_file()
    if _cache["file"] != f:
        _cache.update(file=f, mtime=None, data={})
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != mtime:
        try:
            _cache["data"] = json.load(f.open(encoding="utf-8"))
            _cache["mtime"] = mtime
        except (OSError, ValueError):
            return _cache["data"]
    return _cache["data"]


def save(values):
    """Write settings, into the checkout's config.json or the user's folder."""
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    current = dict(config())
    current.update(values)
    f.write_text(json.dumps(current, indent=2), encoding="utf-8")
    _cache["mtime"] = None
    return f


def setting(name, default=None):
    v = config().get(name)
    return v if v not in (None, "") else (FALLBACK.get(name) if default is None else default)


def game():
    """The working game: the only install the studio ever writes into.

    An empty path means the setup has not run yet. Callers say so rather than
    guessing."""
    return pathlib.Path(os.path.expandvars(str(setting("gamePath") or "")))


def game_set():
    """Has a game been chosen at all? (An unset path is not ".", the current folder.)"""
    return bool(str(setting("gamePath") or "").strip())


def have_game():
    return game_set() and (game() / "missions" / "location0").is_dir()


def require_game():
    """The game, for a command that cannot do without one."""
    if not game_set():
        raise SystemExit("the studio has not been pointed at the game yet:\n"
                         "  python -m studio setup --game <folder>")
    return game()


def pristine():
    """The untouched original the studio reads and never writes.

    In order: what the settings name, then our own snapshot of the user's
    install, then the working game itself."""
    p = setting("pristinePath")
    if p:
        return pathlib.Path(os.path.expandvars(str(p)))
    snap = snapshot()
    if (snap / "missions" / "location0").is_dir():
        return snap
    return game()


def snapshot():
    """Our own copy of the parts of the game a mission is rebuilt from."""
    return home() / "pristine"


def levels(game_arg=None):
    """Where the level data is read from.

    Our own reference copy, which is the point of having one: it is the game
    as it was when you connected it, and it is still there when the game is
    not (a drive unplugged, the game moved or uninstalled). The game itself is
    used only when there is no reference yet.

    Writes never come here. Those go to game(), and nowhere else.
    """
    snap = snapshot()
    if (snap / "missions" / "location0").is_dir():
        return snap
    if game_arg and (pathlib.Path(game_arg) / "missions" / "location0").is_dir():
        return pathlib.Path(game_arg)
    return game()


def game_missing():
    """True when a game was set up and its folder is no longer there."""
    return game_set() and not (game() / "missions" / "location0").is_dir()


def decompiled():
    """Where levels read out of the game are kept, so they are read once."""
    return home() / "decompiled"


def slot():
    return int(setting("slot", 15))


def data():
    """The level data the editor shows: made from the person's own game, kept in
    their folder. It is never part of the program or the repository."""
    return home() / "data"


def checkout():
    """True when running from a checkout of the repository with its own settings.

    A checkout keeps what it writes beside the code, as it always has, so
    working on the project never touches an installed copy. An installed copy
    keeps everything it writes in the user's folder, because the folder a
    program is installed in is not the user's to write to."""
    return not os.environ.get("IGISTUDIO_HOME") and (ROOT / "config.json").exists()


def writable():
    """The root of everything the studio writes (other than into the game)."""
    return ROOT if checkout() else home()


def missions():
    """Where the user's own missions (and saved groups) are kept."""
    if checkout() and (ROOT / "missions" / "custom").is_dir():
        return ROOT / "missions"
    return home() / "missions"


def work():
    """Where a build stages its output before it is installed."""
    return ROOT / "missions" if checkout() else home() / "work"


def backups():
    """Copies of the game's own files, taken before the studio first changes one."""
    return writable() / "backups"


def corpus():
    return ROOT / "corpus"


def cache():
    """Things worth keeping between runs that can always be made again."""
    return writable() / "cache"
