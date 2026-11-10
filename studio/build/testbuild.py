# A mission built into the test copy of the game, for trying it (studio/server/gametest.py).
#
# It runs as a process of its own, started with IGISTUDIO_GAME and IGISTUDIO_TESTRUN
# in its environment. To this process the test copy is the connected game, and its
# missions, backups and work folder are private ones inside the copy. So everything
# below is the studio's ordinary Apply, and it has no way to touch the person's game,
# their mission's record of where it is installed, or the backups of their game.
#
#   python -m studio.build.testbuild --source <mission folder> --game <test copy>
#                                    [--options <json file>]
#
# options: {"start": {x, y, z, gamma}, "tour": [shot, ...], "probes": [{label, expr}], "probe_base": n,
#           "width": 1024, "height": 768}
# Says RESULT {...} on its last line.
import argparse, json, os, pathlib, re, shutil, sys

from studio import paths
from studio.qvm import read as QR, write as QW
from studio.server import missions as MS
from studio.build import slots as SL


def private_copy(source, options):
    """The mission, in this run's own library. A tour replaces its intro for this build."""
    mid = source.name
    dst = MS.STORE / mid
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dst, ignore=shutil.ignore_patterns("history", "ai", "build-plan.json"))
    f = dst / "mission.json"
    m = json.loads(f.read_text(encoding="utf-8"))
    m.pop("installed", None)
    m.pop("applied", None)
    m["slot"] = None
    if options.get("probes"):
        plan = m.setdefault("plan", {})
        plan["_probes"] = options["probes"]
        plan["_probe_base"] = options.get("probe_base")
    if options.get("explode"):
        m.setdefault("plan", {})["_explode"] = options["explode"]
    tour = options.get("tour")
    if tour:
        plan = m.setdefault("plan", {})
        plan["cutscenes"] = [c for c in (plan.get("cutscenes") or []) if isinstance(c, dict) and c.get("where") != "intro"]
        plan["cutscenes"].insert(0, {"uid": "testtour", "name": "Test tour", "where": "intro", "letterbox": False,
                                     "skippable": False, "shots": tour})
    f.write_text(json.dumps(m), encoding="utf-8")
    return mid


def clear_other_slots(game, mid):
    """The copy holds the mission under test and no other, so it doesn't fill the disk."""
    for s in SL.list_slots(game):
        mk = s.get("marker") or {}
        if s["custom"] and mk and mk.get("missionId") != mid:
            SL.delete_slot(game, s["level"], log=print)


def set_up_game(game, slot, width, height):
    """The test copy opens its mission list on this mission, in a window of this size."""
    f = pathlib.Path(game) / "config.qvm"
    src = QR.decompile(QR.parse(str(f)))
    src = re.sub(r"GOActiveMission\(\d+\)", "GOActiveMission(%d)" % slot, src, count=1)
    src, n = re.subn(r"GOGfxDisp\(\d+, *\d+, *(\d+)\)", lambda m: "GOGfxDisp(%d, %d, %s)" % (width, height, m.group(1)), src, count=1)
    if not n:
        print("the game's settings have no display line: the window keeps the size it has")
    f.write_bytes(QW.compile_text(src))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--game", required=True)
    ap.add_argument("--options")
    a = ap.parse_args()
    if not os.environ.get("IGISTUDIO_TESTRUN") or paths.game().resolve() != pathlib.Path(a.game).resolve():
        sys.exit("this only runs on the test copy of the game")
    options = json.loads(pathlib.Path(a.options).read_text(encoding="utf-8")) if a.options else {}
    mid = private_copy(pathlib.Path(a.source), options)
    clear_other_slots(a.game, mid)
    # the ordinary Apply; only ever imported here, once this process's game is the copy
    from studio.server import app as APP
    real = APP.load_config

    def on_the_copy():
        cfg = real()
        cfg["gamePath"] = a.game
        return cfg
    APP.load_config = on_the_copy
    res = APP.apply_mission(mid, test=options.get("start") or None, say=print)
    if res.get("slot") and (res.get("ok") or res.get("installed")):
        set_up_game(a.game, int(res["slot"]), int(options.get("width") or 1024), int(options.get("height") or 768))
    print("RESULT " + json.dumps({"ok": bool(res.get("ok")), "slot": res.get("slot"), "error": res.get("error")}), flush=True)


if __name__ == "__main__":
    main()
