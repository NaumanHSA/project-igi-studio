# Compares the working game with an untouched copy, and puts back what drifted.
#
#   python -m studio setup --check-game          say what differs
#   python -m studio setup --repair              put the built-in missions back
#
# The studio never writes to a built-in mission, but earlier tools did, and a
# person may have modded theirs. A mission built on a level that is not the
# level it shipped as will not behave as the editor showed it, so it is worth
# knowing, and worth being able to undo.
#
# Only a file that comes from an untouched install and lands at the same place
# in the tree is ever written, through protect.assert_restore, so a repair can
# only make the game more like the original.
#
# The mission strings are the exception that is not drift: the studio adds its
# own keys to language/<lang>/objectives.res under MS<slot>_, so those files
# are expected to differ and are left alone.
import filecmp, pathlib, re, shutil

from studio import paths, protect
from studio.setup import verify

LEVELS = range(1, 15)


def _pairs(game, source):
    """The built-in files that exist in both, as (relative path, source, target)."""
    game, source = pathlib.Path(game), pathlib.Path(source)
    out = []
    for n in LEVELS:
        rel_level = pathlib.Path("missions") / "location0" / ("level%d" % n)
        base = source / rel_level
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(source)
            t = game / rel
            if t.is_file():
                out.append((rel, f, t))
    return out


def _chained_to(path):
    """The slot a mission.qvm sends the player to next, when it names one.

    Making mission 14 lead to mission 15 is how a custom mission is reached
    from the campaign. It is a deliberate change to a built-in mission, so a
    repair must recognise it instead of quietly undoing it.
    """
    try:
        from studio.qvm import read as R
        text = R.decompile(R.parse(path))
    except Exception:
        return None
    m = re.search(r'DefineMission\(\s*\d+\s*,[^,]*,[^,]*,[^,]*,\s*([A-Za-z0-9_]+)', text)
    if not m:
        return None
    return int(m.group(1)) if m.group(1).isdigit() else None


def differences(game=None, source=None, deep=False):
    """Built-in files of the working game that are not what the original has.

    deep compares the bytes; otherwise size and time, which is much quicker.
    Each one says whether it is drift (put it back) or a deliberate chain to a
    custom mission (leave it alone).
    """
    game = pathlib.Path(game or paths.game())
    source = pathlib.Path(source or paths.pristine())
    out = []
    for rel, src, dst in _pairs(game, source):
        if filecmp.cmp(str(src), str(dst), shallow=not deep):
            continue
        d = {"file": str(rel).replace("\\", "/"), "kind": "drift",
             "size": dst.stat().st_size, "was": src.stat().st_size, "note": ""}
        if dst.name.lower() == "mission.qvm":
            now, before = _chained_to(dst), _chained_to(src)
            if now and now >= protect.FIRST_CUSTOM and now != before:
                d["kind"] = "chain"
                d["note"] = ("it sends the player to mission %d after this one, "
                             "which is how a custom mission is reached from the campaign" % now)
        out.append(d)
    return out


def repair(game=None, source=None, only=None, log=print):
    """Put those files back. Returns the list restored."""
    game = pathlib.Path(game or paths.game())
    source = pathlib.Path(source or paths.pristine())
    want = set(only or [])
    done = []
    for d in differences(game, source, deep=True):
        if want:
            if d["file"] not in want:
                continue
        elif d["kind"] != "drift":
            log("left alone: %s, %s" % (d["file"], d["note"]))
            continue
        src, dst = source / d["file"], game / d["file"]
        protect.assert_restore(dst, src)          # refuses anything but putting it back
        backup = dst.with_suffix(dst.suffix + ".before-repair")
        if not backup.exists():
            shutil.copyfile(dst, backup)
        shutil.copyfile(src, dst)
        log("put back %s (kept the old one as %s)" % (d["file"], backup.name))
        done.append(d["file"])
    if not done:
        log("nothing to put back: every built-in mission is as it shipped")
    return done


if __name__ == "__main__":
    import sys
    game, source = paths.game(), paths.pristine()
    print("working game   %s" % game)
    print("original       %s" % source)
    if not verify.check(source, deep=False)["ok"]:
        raise SystemExit("the original copy at %s is not usable; run the setup first" % source)
    diffs = differences(game, source, deep="--deep" in sys.argv)
    if not diffs:
        print("\nevery built-in mission is as it shipped")
    else:
        drift = [d for d in diffs if d["kind"] == "drift"]
        print("\n%d built-in file(s) differ:" % len(diffs))
        for d in diffs:
            print("  %-44s %8d bytes, originally %8d  %s"
                  % (d["file"], d["size"], d["was"], "" if d["kind"] == "drift" else "(on purpose)"))
            if d["note"]:
                print("      %s" % d["note"])
        if not drift:
            print("\nnothing has drifted: every difference is deliberate")
            raise SystemExit(0)
        if "--repair" in sys.argv:
            print()
            repair(game, source)
        else:
            print("\nto put them back:  python -m studio setup --repair")
