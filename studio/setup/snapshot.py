# Our own copy of the parts of the game a mission is rebuilt from.
#
#   python -m studio setup --snapshot
#   from studio.setup import snapshot
#   snapshot.make(game, log=print)
#
# Why a copy at all: every mission is built from the original level, so the
# studio needs those files to stay as they shipped. It never writes to them,
# but the person may mod their game later, and then missions built afterwards
# would quietly differ from missions built before. A copy of the small parts
# settles that, and it is theirs, on their machine: nothing is downloaded and
# nothing is shipped.
#
# What is copied, and what is not:
#
#   level scripts, AI scripts, graphs, terrain, language      about 64 MB
#   each level's model archive (models/<level>.res)           about 103 MB
#   textures, sounds, lightmaps                               not copied
#
# The model archives are there because a build asks what every placed object
# stands on, a floor or the ground, and the answer is in the buildings' meshes.
# Without them a crate on a roof would be built as a crate on the ground, and a
# build from the reference would not be the build from the game. Textures,
# sounds and lightmaps are never read by a build.
import hashlib, json, pathlib, shutil, time

from studio import paths
from studio.setup import verify

LEVELS = range(1, 15)
#: per level: these folders whole, plus the level's own files
FOLDERS = ("ai", "graphs", "terrain", "models")
SKIP_SUFFIX = (".tex", ".tga", ".wav", ".mef")     # nothing large sneaks in


def plan(game):
    """(files to copy, total bytes). Nothing is written."""
    game = pathlib.Path(game)
    items, total = [], 0
    loc0 = game / "missions" / "location0"
    for n in LEVELS:
        lv = loc0 / ("level%d" % n)
        if not lv.is_dir():
            continue
        for f in sorted(lv.glob("*")):
            if f.is_file():
                items.append(f)
        for sub in FOLDERS:
            d = lv / sub
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file() and f.suffix.lower() not in SKIP_SUFFIX:
                        items.append(f)
    lang = game / "language"
    if lang.is_dir():
        for f in sorted(lang.rglob("*.res")):
            items.append(f)
    for f in items:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return items, total


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def base_fingerprint(where):
    """The levels themselves, and nothing else.

    Used to tell whether the reference is still the game it was taken from. It
    leaves out the language files and the executable on purpose: the studio
    writes its own mission strings into the game, and that must not make the
    reference look out of date.
    """
    where = pathlib.Path(where)
    parts = []
    for n in LEVELS:
        p = where / "missions" / "location0" / ("level%d" % n) / "objects.qvm"
        parts.append("level%d %s" % (n, _sha(p) if p.is_file() else "-"))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def check_copy(game, dest=None, log=None):
    """Compare every copied file with the one it came from. Returns the bad ones."""
    game = pathlib.Path(game)
    dest = pathlib.Path(dest or paths.snapshot())
    items, _ = plan(game)
    bad = []
    for i, f in enumerate(items):
        out = dest / f.relative_to(game)
        if not out.is_file():
            bad.append((str(f.relative_to(game)), "not copied"))
        elif out.stat().st_size != f.stat().st_size or _sha(out) != _sha(f):
            bad.append((str(f.relative_to(game)), "does not match"))
        if log and i and i % 400 == 0:
            log("  checked %d of %d" % (i, len(items)))
    return bad


def make(game, dest=None, log=print, force=False, check=True):
    """Copy those parts to dest (the user's folder by default), and check them.

    Nothing is written to the game before this has run: it is the reference
    every later build starts from, so it is made first and verified before it
    is trusted.
    """
    game = pathlib.Path(game)
    dest = pathlib.Path(dest or paths.snapshot())
    items, total = plan(game)
    if not items:
        raise ValueError("nothing to copy from %s: is that a copy of the game?" % game)
    log("copying %d files, %.0f MB, from %s" % (len(items), total / 1e6, game))
    done = copied = 0
    for f in items:
        rel = f.relative_to(game)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if force or not out.exists() or out.stat().st_size != f.stat().st_size:
            shutil.copyfile(f, out)
            copied += 1
        done += 1
        if done % 200 == 0:
            log("  %d of %d" % (done, len(items)))
    bad = []
    if check:
        log("checking the copy, file by file")
        bad = check_copy(game, dest, log=log)
        if bad:
            for name, why in bad[:5]:
                log("  %s: %s" % (name, why))
            raise IOError("the reference copy is not complete: %d file(s) wrong, first is %s"
                          % (len(bad), bad[0][0]))
    fp, _ = verify.fingerprint(game)
    info = {"from": str(game), "made": int(time.time()), "files": len(items),
            "bytes": total, "fingerprint": fp, "levels": base_fingerprint(game),
            "checked": bool(check)}
    (dest / "snapshot.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    log("reference ready at %s (%d file(s) copied, %d checked)" % (dest, copied, len(items)))
    return info


def info(dest=None):
    """What the snapshot holds, or None when there is none."""
    dest = pathlib.Path(dest or paths.snapshot())
    try:
        return json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stale(game=None, dest=None):
    """True when the game's own levels are no longer the ones we copied.

    Only the levels are compared. The studio writes its missions and their
    strings into the game, and that is not the reference going out of date.
    """
    i = info(dest)
    if not i:
        return None
    where = pathlib.Path(game or paths.game())
    if not (where / "missions" / "location0").is_dir():
        return None
    if i.get("levels"):
        return base_fingerprint(where) != i["levels"]
    return verify.fingerprint(where)[0] != i.get("fingerprint")


def ready(game=None, dest=None):
    """Is there a checked reference covering the levels of this game?"""
    i = info(dest)
    if not i or not i.get("files"):
        return False
    dest = pathlib.Path(dest or paths.snapshot())
    for n in LEVELS:
        if not (dest / "missions" / "location0" / ("level%d" % n) / "objects.qvm").is_file():
            return False
    return True


if __name__ == "__main__":
    import sys
    game = sys.argv[1] if len(sys.argv) > 1 else paths.game()
    items, total = plan(game)
    print("%d files, %.0f MB would be copied to %s" % (len(items), total / 1e6, paths.snapshot()))
