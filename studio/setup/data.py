# Builds the level data the editor shows, from the person's own game.
#
#   python -m studio setup --data          build it (about a minute or two)
#   from studio.setup import data
#   data.build(log=print)
#
# The editor draws the fourteen levels, their walkways, their ground and their
# buildings. All of that comes out of the game, so none of it ships with the
# studio: it is made here, on the person's machine, from their own copy, and
# kept in their folder (studio.paths.data()).
#
# Most of it is read from the studio's reference copy of the levels. Three
# things are only in the game itself, and are read from there: the shared
# model archive every level borrows from, the terrain textures, and the covers
# in the game's own menu.
import json, os, pathlib, subprocess, sys, time

from studio import paths
from studio.setup import snapshot

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: In order: later steps read what earlier ones wrote.
STEPS = [
    # name, module, reads, what it makes, extra arguments
    ("levels", "studio.extract.levels", None, "the objects of every level", []),
    ("graphs", "studio.extract.graphs", "reference", "the walkways the guards use", []),
    ("models", "studio.extract.models", "game", "every model's size and name", []),
    ("catalog", "studio.extract.catalog", None, "the inventory of things to place", []),
    # a 1 m grid: the editor places things, and snaps them to the ground, by the metre
    ("terrain", "studio.extract.terrain", "reference", "the height of the ground", ["--cell", "1"]),
    ("ground", "studio.extract.ground", "game", "what the ground is made of", []),
    ("meshes", "studio.extract.meshes", "game", "the buildings, seen from above", []),
    ("navtemplates", "studio.build.navtemplates", "reference", "the walkways inside buildings", []),
    ("library", "studio.extract.library", "game", "the missions' names and covers", []),
]

#: What must be there for the editor to work. Checked, not assumed.
REQUIRED = (["index.json", "models.json", "catalog.json", "meshes.bin", "meshes.json",
             "navtemplates.json", "builtins.json"]
            + ["level%d.json" % n for n in range(1, 15)]
            + ["graphs%d.json" % n for n in range(1, 15)])

STAMP = "data.json"
VERSION = 1          # bump when an extractor's output changes, so data is rebuilt


def _run(module, args, log):
    """Run one extractor, passing on each line it prints as it prints it, so a
    step that takes a minute still shows it is moving."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    p = subprocess.Popen([sys.executable, "-m", module] + args, cwd=str(ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        if not line.strip():
            continue
        tail = (tail + [line])[-8:]
        log("    " + line.strip())
    if p.wait() != 0:
        raise RuntimeError("%s failed:\n%s" % (module, "\n".join(tail[-6:])))


def build(game=None, log=print):
    """Make every file the editor needs. Stops at the first step that fails."""
    game = pathlib.Path(game or paths.game())
    if not (game / "missions" / "location0").is_dir():
        raise FileNotFoundError("the game is not at %s, and part of the level data "
                                "can only be read from the game itself" % game)
    ref = paths.snapshot() if snapshot.ready() else game
    out = paths.data()
    out.mkdir(parents=True, exist_ok=True)
    log("building the level data into %s" % out)
    t0 = time.time()
    for i, (name, module, reads, what, extra) in enumerate(STEPS, 1):
        log("STAGE %d of %d: %s" % (i, len(STEPS), what))
        args = []
        if reads == "game":
            args = ["--game", str(game)]
        elif reads == "reference":
            args = ["--game", str(ref)]
        t = time.time()
        _run(module, args + list(extra), log)
        log("  %s done in %.0fs" % (name, time.time() - t))
    missing = [f for f in REQUIRED if not (out / f).exists()]
    if missing:
        raise RuntimeError("the level data is incomplete, missing: %s" % ", ".join(missing[:6]))
    stamp = {"version": VERSION, "built": int(time.time()), "game": str(game),
             "levels": snapshot.base_fingerprint(ref), "seconds": round(time.time() - t0)}
    (out / STAMP).write_text(json.dumps(stamp, indent=1), encoding="utf-8")
    log("level data ready in %.0fs" % (time.time() - t0))
    return stamp


def info():
    try:
        return json.loads((paths.data() / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ready():
    """Is the level data there, complete, and made by this version of the studio?"""
    i = info()
    if not i or i.get("version") != VERSION:
        return False
    return all((paths.data() / f).exists() for f in REQUIRED)


if __name__ == "__main__":
    build()
