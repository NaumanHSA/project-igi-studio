# The game's recorded flights, to place in a mission of your own.
#
#   python -m studio.extract.flights [--game <reference game>] [--out <folder>]
#
# Each helicopter and plane of the fourteen levels that flies a recorded drive
# (an AnimTask: control inputs, so the flight goes from wherever the aircraft
# starts, turned the way it starts) -> flights.json in the level data:
#   [{level, id, kind, model, name, seconds, x, y, z, rot, rel, role, takeoff}]
# rel is how high over the ground it starts (from the level's own terrain), so a
# flight placed elsewhere starts as high over the ground there; takeoff is a
# start on the ground. role is the cutscene it flew in ("intro", "outro"), or ""
# for one in play. Read from the levels' "motion" (studio/extract/levels.py).
import json, pathlib, sys

from studio import paths
from studio.build.terrain import Terrain
from studio.qvm import source as qvm_source

argv = sys.argv
GAME = pathlib.Path(argv[argv.index("--game") + 1]) if "--game" in argv else paths.game()
OUT = pathlib.Path(argv[argv.index("--out") + 1]) if "--out" in argv else paths.data()

out = []
for lv in range(1, 15):
    f = OUT / ("level%d.json" % lv)
    if not f.exists():
        continue
    d = json.load(f.open())
    m = d.get("motion") or {}
    roles = {c["id"]: c["role"] for c in m.get("cutscenes") or []}
    fl = [v for v in m.get("vehicles") or [] if v["kind"] in ("heli", "plane") and v.get("drives") and v.get("x") is not None]
    if not fl:
        continue
    try:
        t = Terrain(GAME / "missions" / "location0" / ("level%d" % lv), qvm_source.level_qsc(lv, str(GAME)))
    except Exception as e:                              # noqa: BLE001 - a level we cannot read is left out
        print("level %d: no terrain (%s)" % (lv, e))
        continue
    for v in fl:
        g = t.z(v["x"], v["y"])
        rel = round(v["z"] - g, 2) if g is not None else None
        out.append({"level": lv, "id": v["id"], "kind": v["kind"], "model": v["model"], "name": v["name"],
                    "seconds": round(sum(x["seconds"] for x in v["drives"]), 1), "x": v["x"], "y": v["y"], "z": v["z"],
                    "rot": v.get("rot") or [0, 0, 0], "rel": rel, "role": roles.get(v.get("cutscene"), ""),
                    "takeoff": rel is not None and rel < 4.0})
    print("level %-2d %d flight(s)" % (lv, len(fl)))
(OUT / "flights.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
print("wrote %d flights to %s" % (len(out), OUT / "flights.json"))
