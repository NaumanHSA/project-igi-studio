# The setup, from a terminal. The editor does the same through /api/setup.
#
#   python -m studio setup                    what the studio knows and what it needs
#   python -m studio setup --find             copies of the game on this machine
#   python -m studio setup --game <folder>    use that one (it is checked first)
#   python -m studio setup --snapshot         copy the parts a mission is rebuilt from
#   python -m studio setup --data             build the level data the editor shows
#   python -m studio setup --check-game       has anything in the built-in missions drifted
#   python -m studio setup --repair           put the drifted ones back
#   python -m studio setup --name "<build>"   remember this install as a known build
import sys

from studio import paths
from studio.setup import data, detect, repair, snapshot, verify


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and len(sys.argv) > sys.argv.index(name) + 1 else default


def status():
    g = paths.game()
    print("settings     %s" % paths.config_file())
    print("your folder  %s" % paths.home())
    if not paths.have_game():
        print("\nThe game has not been found yet.")
        found = detect.find()
        if found:
            print("These look like copies of it:")
            for h in found:
                print("   %-44s %s" % (h["path"], h["where"]))
            print("\nUse one with:  python -m studio setup --game \"%s\"" % found[0]["path"])
        else:
            print("Nothing found. Point the studio at it with:\n"
                  "  python -m studio setup --game \"C:\\path\\to\\Project IGI\"")
        return 1

    r = verify.check(g)
    print("\nthe game     %s" % g)
    print("             %d built-in missions, custom slots: %s"
          % (r["levels"], ", ".join(str(n) for n in r["custom"]) or "none"))
    print("             build: %s" % (r["profileName"] or "not one we know"))
    if not r["profileName"] and r.get("nearest"):
        print("             closest known: %s (%d file(s) differ)" % (r["nearest"], r["differs"]))
    for m in r["missing"]:
        print("   missing:  %s" % m)

    snap = snapshot.info()
    print()
    if snap:
        import time as _t
        print("reference    %s" % paths.snapshot())
        print("             %d files, %.0f MB, taken %s from %s%s"
              % (snap["files"], snap["bytes"] / 1e6,
                 _t.strftime("%Y-%m-%d", _t.localtime(snap["made"])), snap["from"],
                 ", checked file by file" if snap.get("checked") else ""))
        if snapshot.stale(g):
            print("             the game's levels have changed since this was taken.")
            print("             What differs:  python -m studio setup --check-game")
    else:
        items, total = snapshot.plan(g)
        print("reference    none yet. Nothing is written to the game without one.")
        print("             Make it:  python -m studio setup --snapshot   (%d files, %.0f MB)"
              % (len(items), total / 1e6))
    di = data.info()
    if di and data.ready():
        print("level data   %s, built in %ds" % (paths.data(), di.get("seconds", 0)))
    else:
        print("level data   not built yet:  python -m studio setup --data")
    return 0


def set_game(path):
    """Connect a game: check it, copy the reference out of it, then use it.

    The copy comes before anything else. It is what every mission is later
    rebuilt from, so it is taken while the game is still as the person had it,
    and it is verified file by file before the studio writes anything.
    """
    r = verify.check(path)
    if not r["ok"]:
        print("that folder cannot be used as the game:")
        for m in r["missing"]:
            print("   missing: %s" % m)
        return 2
    print("the game     %s" % r["path"])
    print("build        %s" % (r["profileName"] or "not one we know (fingerprint %s)" % r["fingerprint"]))
    print("\nmaking the studio's own reference copy first")
    try:
        info = snapshot.make(r["path"], log=lambda m: print("   %s" % m))
    except (IOError, OSError, ValueError) as e:
        print("\nthe reference copy failed: %s" % e)
        print("the game has not been connected: nothing will be written to it without one")
        return 3
    print("\nbuilding the level data the editor shows")
    try:
        data.build(r["path"], log=lambda m: print("   %s" % m))
    except (OSError, RuntimeError) as e:
        print("\nthe level data could not be built: %s" % e)
        print("the game has not been connected")
        return 4
    paths.save({"gamePath": r["path"], "pristinePath": "", "protectedPaths": []})
    print("\nconnected. Missions are written to %s" % r["path"])
    print("the reference lives in %s (%d files, %.0f MB, checked)"
          % (paths.snapshot(), info["files"], info["bytes"] / 1e6))
    return 0


def main():
    if "--find" in sys.argv:
        for h in detect.find():
            print("%-44s %s" % (h["path"], h["where"]))
        return 0
    if arg("--game"):
        return set_game(arg("--game"))
    if arg("--pristine"):
        paths.save({"pristinePath": arg("--pristine")})
        print("the original is %s" % paths.pristine())
        return 0
    if "--snapshot" in sys.argv:
        if not paths.have_game():
            print("the game has not been found yet: python -m studio setup --game <folder>")
            return 2
        print("copying the reference from %s" % paths.game())
        try:
            snapshot.make(paths.game(), force="--force" in sys.argv)
        except (IOError, OSError, ValueError) as e:
            print("the reference copy failed: %s" % e)
            return 3
        return 0
    if "--data" in sys.argv:
        if not paths.have_game():
            print("the game is not there; the level data is read out of it")
            return 2
        try:
            data.build(paths.game())
        except (OSError, RuntimeError) as e:
            print("the level data could not be built: %s" % e)
            return 4
        return 0
    if arg("--name"):
        fp = verify.record(paths.game(), arg("--name"), arg("--notes") or "")
        print("remembered %s as %s" % (fp, arg("--name")))
        return 0
    if "--check-game" in sys.argv or "--repair" in sys.argv:
        sys.argv.append("--deep")
        import runpy
        runpy.run_module("studio.setup.repair", run_name="__main__")
        return 0
    return status()


if __name__ == "__main__":
    sys.exit(main())
